"""Test sur le passé, en conditions réelles : le modèle ne voit que les matchs déjà joués.

Produit docs/data/backtest.json (affiché dans l'appli) et data/state/model_config.json (poids du mélange).
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from config import COUPONS, LEAGUES, SITE_DATA, STATE_DIR, VALUE_EDGE
from coupons import SMALL_KINDS, build_day, favorite_leg, leg_family, legs_for_match, settle_coupon, signature
import extra
import meta
from coupons import settle_leg
from model import devig, fit, markets_from_total, predict, result_probs, score_matrix, total_dist

VERSION = 10  # à augmenter quand le test change, pour qu'il soit relancé sans attendre la semaine
BACKTEST_YEARS = 3.2
REFIT_DAYS = 7


def walk_forward(results: pd.DataFrame, today: pd.Timestamp) -> pd.DataFrame:
    rows = []
    start = today - pd.Timedelta(days=int(BACKTEST_YEARS * 365))
    for div in LEAGUES:
        m = results[results["div"] == div]
        if m.empty:
            continue
        t = max(start, m["date"].min() + pd.Timedelta(days=500))
        while t < today:
            nxt = t + pd.Timedelta(days=REFIT_DAYS)
            week = m[(m["date"] >= t) & (m["date"] < nxt)]
            if len(week):
                r = fit(m, t)
                if r is not None:
                    for row in week.itertuples():
                        lh, la = r.rates(row.home, row.away)
                        mat = score_matrix(lh, la, r.rho)
                        mod, rp = markets_from_total(total_dist(mat)), result_probs(mat)
                        rows.append({
                            "div": div, "date": row.date, "home": row.home, "away": row.away,
                            "hg": row.hg, "ag": row.ag, "lh": lh, "la": la, "rho": r.rho,
                            "o25": row.o25, "u25": row.u25, "o25_max": row.o25_max,
                            "o25_close": row.o25_close, "u25_close": row.u25_close,
                            "m_o15": mod["o15"], "m_o25": mod["o25"],
                            "oh": row.oh, "od": row.od, "oa": row.oa,
                            "fav_m": abs(rp["1"] - rp["2"]),
                            "hthg": row.hthg, "htag": row.htag,
                        })
            t = nxt
    return pd.DataFrame(rows)


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def calibration(p, y, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (p >= lo) & (p < hi)
        if sel.sum() >= 30:
            out.append({"pred": round(float(p[sel].mean()), 3), "obs": round(float(y[sel].mean()), 3), "n": int(sel.sum())})
    return out


MK_LABEL = {"o15": "+1,5", "o20": "+2 (asiatique)", "o25": "+2,5"}
BANDS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


def diagnostic(bt: pd.DataFrame):
    """Taux de réussite réel contre prévu des sélections, par ligue × marché et par niveau de confiance.

    Les cases nettement sous le prévu (assez de matchs, écart significatif) sont écartées des coupons.
    """
    rows = []
    for r in bt.itertuples():
        for l in r.legs:
            if l["p_win"] < 0.5 or l["market"] == "o20" or l["market"] in extra.EXTRA:  # +2 = +2,5 gagné ou remboursé ; autres paris : bloc à part
                continue
            res = settle_leg(l["market"], r.tot, r.hg, r.ag)
            rows.append((r.div, l["market"], l["p_win"], l["p_push"], res == "won", res == "push", l["odds"]))
    d = pd.DataFrame(rows, columns=["div", "market", "p", "push_p", "won", "push", "odds"])
    out = {"segments": [], "bands": [], "odds": []}
    blocked = []
    for (div, mk), g in d.groupby(["div", "market"]):
        n, pred, obs = len(g), float(g["p"].mean()), float(g["won"].mean())
        se = float(np.sqrt(max(pred * (1 - pred), 1e-6) / n))
        z = (obs - pred) / se
        weak = n >= 150 and obs - pred <= -0.03 and z <= -2
        if weak:
            blocked.append(f"{div}|{mk}")
        out["segments"].append({"div": div, "name": LEAGUES[div][0], "market": MK_LABEL.get(mk, mk), "n": n,
                                "pred": round(pred, 3), "obs": round(obs, 3), "z": round(z, 1), "blocked": weak})
    for mk, g0 in d.groupby("market"):
        for lo, hi in BANDS:
            g = g0[(g0["p"] >= lo) & (g0["p"] < hi)]
            if len(g) >= 50:
                out["bands"].append({"market": MK_LABEL.get(mk, mk), "band": f"{round(lo * 100)}–{min(100, round(hi * 100))} %",
                                     "n": int(len(g)), "pred": round(float(g["p"].mean()), 3), "obs": round(float(g["won"].mean()), 3)})
    for lo, hi in ((1.0, 1.2), (1.2, 1.4), (1.4, 1.7), (1.7, 2.2), (2.2, 99)):
        g = d[(d["odds"] >= lo) & (d["odds"] < hi)]
        if len(g) >= 50:
            ret = np.where(g["won"], g["odds"], np.where(g["push"], 1.0, 0.0))
            out["odds"].append({"range": f"{lo:.1f}–{hi:.1f}".replace(".", ",") if hi < 99 else f"{lo:.1f} et +".replace(".", ","),
                                "n": int(len(g)), "pred": round(float(g["p"].mean()), 3), "obs": round(float(g["won"].mean()), 3),
                                "roi": round(float(ret.mean() - 1), 3)})
    out["blocked"] = blocked
    return out, blocked


def match_info(r) -> dict:
    """Score de mi-temps d'un match joué, s'il est publié (sert aux paris de mi-temps)."""
    if pd.isna(r.hthg) or pd.isna(r.htag):
        return {}
    return {"ht": (int(r.hthg), int(r.htag))}


class _R:  # notes figées pour rejouer predict() sur une ligne du backtest
    def __init__(self, lh, la, rho):
        self._lh, self._la, self.rho = lh, la, rho

    def rates(self, *_):
        return self._lh, self._la


def run(results: pd.DataFrame, today: date) -> dict:
    today = pd.Timestamp(today)
    bt = walk_forward(results, today)
    bt["tot"] = bt["hg"] + bt["ag"]
    bt["y15"] = (bt["tot"] >= 2).astype(float)
    bt["y25"] = (bt["tot"] >= 3).astype(float)
    bt["mkt"] = [devig(o, u) for o, u in zip(bt["o25"], bt["u25"])]
    has = bt["mkt"].notna()

    # Poids du modèle dans le mélange avec le marché
    sub = bt[has]
    grid = np.round(np.linspace(0, 1, 11), 2)
    scores = {float(w): logloss(w * sub["m_o25"] + (1 - w) * sub["mkt"].astype(float), sub["y25"]) for w in grid}
    blend = min(scores, key=scores.get)

    # Autres paris : part des buts marqués en 1re mi-temps
    ht_ok = results.dropna(subset=["hthg", "htag"])
    ht_share = float((ht_ok["hthg"] + ht_ok["htag"]).sum() / max((ht_ok["hg"] + ht_ok["ag"]).sum(), 1))
    finals, legs_all, base, favs, xraw = [], [], [], [], []
    for row in bt.itertuples():
        o1x2 = None if any(pd.isna(x) for x in (row.oh, row.od, row.oa)) else (row.oh, row.od, row.oa)
        pr = predict(_R(row.lh, row.la, row.rho), "", "", row.o25, row.u25, blend=blend, odds_1x2=o1x2)
        favs.append(favorite_leg(pr, "", "", o1x2))
        mp = predict(_R(row.lh, row.la, row.rho), "", "", row.o25, row.u25, blend=0.0)["final"] if row.mkt is not None and not pd.isna(row.mkt) else None
        base.append((mp["o15"], mp["o25"]) if mp else (np.nan, np.nan))
        finals.append((pr["final"]["o15"], pr["final"]["o25"]))
        legs_all.append(legs_for_match(pr, mp, row.o25 if not pd.isna(row.o25) else None))
        xraw.append((pr["xg_home"], pr["xg_away"], pr["res"]))
    bt["f_o15"] = [f[0] for f in finals]
    bt["f_o25"] = [f[1] for f in finals]
    bt["b_o15"] = [b[0] for b in base]
    bt["b_o25"] = [b[1] for b in base]

    report = {"version": VERSION, "generated": today.strftime("%Y-%m-%d"), "n_matches": int(len(bt)), "blend": blend,
              "period": [bt["date"].min().strftime("%Y-%m-%d"), bt["date"].max().strftime("%Y-%m-%d")],
              "blend_scores": scores, "markets": {}, "leagues": [], "value": {}, "coupons": {}}

    for key, col_m, col_f, y in (("o15", "m_o15", "f_o15", "y15"), ("o25", "m_o25", "f_o25", "y25")):
        yy = bt[y].to_numpy()
        base = np.full_like(yy, yy.mean())
        entry = {
            "n": int(len(bt)), "rate": round(float(yy.mean()), 3),
            "brier_base": round(brier(base, yy), 4),
            "brier_model": round(brier(bt[col_m].to_numpy(), yy), 4),
            "brier_final": round(brier(bt[col_f].to_numpy(), yy), 4),
            "calibration": calibration(bt[col_f].to_numpy(), yy),
        }
        if key == "o25":
            entry["brier_market"] = round(brier(sub["mkt"].astype(float).to_numpy(), sub["y25"].to_numpy()), 4)
        report["markets"][key] = entry

    for div, g in bt.groupby("div"):
        report["leagues"].append({
            "div": div, "name": LEAGUES[div][0], "n": int(len(g)),
            "avg_goals": round(float(g["tot"].mean()), 2),
            "o15_rate": round(float(g["y15"].mean()), 3), "o25_rate": round(float(g["y25"].mean()), 3),
            "o15_pred": round(float(g["f_o15"].mean()), 3), "o25_pred": round(float(g["f_o25"].mean()), 3),
            "brier_o25": round(brier(g["f_o25"].to_numpy(), g["y25"].to_numpy()), 4),
            "skill_o25": round(1 - brier(g["f_o25"].to_numpy(), g["y25"].to_numpy())
                               / max(brier(np.full(len(g), g["y25"].mean()), g["y25"].to_numpy()), 1e-9), 4),
        })

    # Paris simples « value » sur +2,5 avec la cote moyenne du marché
    vb = bt[has & bt["o25"].notna()].copy()
    vb["edge"] = vb["f_o25"] * vb["o25"] - 1
    value = []
    for thr in (0.0, 0.03, 0.05, 0.08):
        s = vb[vb["edge"] >= thr]
        if len(s) == 0:
            continue
        profit = np.where(s["y25"] == 1, s["o25"] - 1, -1.0)
        clv = (s["o25"] / s["o25_close"] - 1).dropna()
        value.append({"threshold": thr, "bets": int(len(s)), "hit": round(float(s["y25"].mean()), 3),
                      "roi": round(float(profit.mean()), 4),
                      "clv": round(float(clv.mean()), 4) if len(clv) else None})
    report["value"]["o25"] = value

    # Autres paris : annoncé / réel par marché, recalibrage, puis sélections ajoutées aux matchs rejoués
    infos = [match_info(r) for r in bt.itertuples()]
    xrows = []
    for r, (xh, xa, res), info in zip(bt.itertuples(), xraw, infos):
        for mk, (pw, pp) in extra.raw_probs(xh, xa, r.rho, res, ht_share).items():
            out = extra.settle(mk, r.hg, r.ag, info)
            if out is not None:  # chance de gagner hors remboursement, comparée aux matchs non remboursés
                xrows.append((r.date, mk, pw / max(1 - pp, 1e-9), 1.0 if out == "won" else 0.0, 1 if out == "push" else 0))
    xcfg = extra.study(pd.DataFrame(xrows, columns=["date", "market", "p", "y", "push"]), today)
    report["extra"] = {"ht_share": round(ht_share, 4), "markets": xcfg}
    for legs, r, (xh, xa, res) in zip(legs_all, bt.itertuples(), xraw):
        legs += extra.legs(xh, xa, r.rho, res, xcfg, ht_share)

    # Jackpots fiables rejoués avec les marchés bien calibrés sur ce test (+1,5, +2,5, favori, autres paris)
    import coupons as coupons_mod
    coupons_mod.RELIABLE = {"o15", "o20", "fav"} | {k for k, e in xcfg.items()
                                                    if (e.get("pred_cal") or e["pred"]) - e["obs"] <= 0.02 and not k.startswith("dnb")}

    # Rejouer les coupons quotidiens (toutes ligues confondues, une journée = une date)
    bt["id"] = [f"{d.strftime('%Y%m%d')}|{dv}|{h}|{a}" for d, dv, h, a in zip(bt["date"], bt["div"], bt["home"], bt["away"])]
    bt["legs"] = legs_all
    bt["fav_leg"] = favs
    stats = {k: {"n": 0, "won": 0, "staked": 0.0, "returned": 0.0, "p_sum": 0.0} for k in COUPONS}
    curve = {k: [] for k in COUPONS}
    combos = {}  # coupons à jouer (2-3 matchs, cote 2) par type de combinaison, et pari qui les a fait casser
    for d, g in bt.groupby("date"):
        matches = [{"id": i, "div": dv, "legs": l, "fav": f} for i, dv, l, f in zip(g["id"], g["div"], g["legs"], g["fav_leg"])]
        scores = {i: (r.hg, r.ag, match_info(r)) for i, r in zip(g["id"], g.itertuples())}
        for c in build_day(matches, league_names={k: v[0] for k, v in LEAGUES.items()}):
            settle_coupon(c, scores)
            s = stats[c["kind"]]
            s["n"] += 1
            s["won"] += c["status"] == "won"
            s["staked"] += 1
            s["returned"] += c["return"]
            s["p_sum"] += c["p_not_lose"]
            curve[c["kind"]].append(round(s["returned"] - s["staked"], 2))
            if c["kind"] in SMALL_KINDS:
                e = combos.setdefault(signature(c), {"n": 0, "won": 0, "p": 0.0, "ret": 0.0, "culprits": {}})
                e["n"] += 1; e["won"] += c["status"] == "won"; e["p"] += c["p_not_lose"]; e["ret"] += c["return"]
                for l in c["legs"]:
                    if l.get("result") == "lost":
                        f = leg_family(l["market"]) if leg_family(l["market"]) != "buts" else MK_LABEL.get(l["market"], l["market"])
                        e["culprits"][f] = e["culprits"].get(f, 0) + 1
    report["combos"] = {sig: {"n": e["n"], "pred": round(e["p"] / e["n"], 3), "hit": round(e["won"] / e["n"], 3),
                              "roi": round(e["ret"] / e["n"] - 1, 3), "culprits": e["culprits"]}
                        for sig, e in sorted(combos.items(), key=lambda x: -x[1]["n"]) if e["n"] >= 30}
    for k, s in stats.items():
        if s["n"] == 0:
            continue
        step = max(1, len(curve[k]) // 120)
        report["coupons"][k] = {
            "label": COUPONS[k]["label"], "n": s["n"], "hit": round(s["won"] / s["n"], 3),
            "pred_hit": round(s["p_sum"] / s["n"], 3),
            "roi": round(s["returned"] / s["staked"] - 1, 4),
            "curve": curve[k][::step],
        }
    # Diagnostic : réussite réelle des sélections selon le réglage (ligue, marché, confiance)
    report["diagnostic"], blocked = diagnostic(bt)

    # Méta-modèle : tirs cadrés + marché + modèle, retenu seulement s'il bat la référence
    try:
        pre, _ = meta.shot_table(results)
        F = [pre.get((r.div, r.date, r.home, r.away), {"sot": 0.0, "shots": 0.0}) for r in bt.itertuples()]
        bt["sot"] = [f["sot"] for f in F]
        bt["shots"] = [f["shots"] for f in F]
        bt["fav"] = [meta._fav(r.oh, r.od, r.oa) for r in bt.itertuples()]
        report["meta"] = meta.study(bt, today)
    except Exception as exc:  # noqa: BLE001
        print("Méta-modèle impossible :", exc)
        report["meta"] = None

    # Facteurs de contexte (classement, période, trêve, fatigue)
    try:
        import context
        cups = context.cup_games_fd(results)
        state = context.team_states(results, cups)
        feats = pd.DataFrame([context.features(r.div, r.date, state(r.div, r.date, r.home), state(r.div, r.date, r.away))
                              for r in bt.itertuples()], index=bt.index)
        report["context"] = context.study(pd.concat([bt[["div", "date", "tot", "f_o15", "f_o25"]], feats], axis=1))
    except Exception as exc:  # noqa: BLE001
        print("Étude de contexte impossible :", exc)
        report["context"] = None

    report["note"] = ("Les cotes +1,5 et +2 ne sont pas dans l'historique : pour les coupons, elles sont estimées "
                      "à partir de la cote +2,5 du marché moins une marge de 6 %. Le taux de réussite est fiable, "
                      "la rentabilité des coupons est une estimation.")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "model_config.json").write_text(json.dumps({"blend": blend, "updated": report["generated"], "context": report.get("context"),
                                                              "meta": report.get("meta"), "blocked": blocked,
                                                              "extra": report.get("extra")}, indent=1))
    (SITE_DATA / "backtest.json").write_text(json.dumps(report, ensure_ascii=False))
    return report
