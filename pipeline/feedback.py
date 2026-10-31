"""Retour d'expérience : nos propres résultats corrigent les prochaines propositions.

Deux mécanismes, recalculés à chaque passage :
1. Calibration par championnat et par marché : si, dans une ligue, le modèle annonce 70 % de +2,5
   et qu'on n'en observe que 62 %, les probabilités suivantes de cette ligue sont baissées.
   Le test sur le passé compte peu (poids 0,25 par match), nos matchs réels comptent pleinement.
2. Fiabilité par championnat : les ligues où le modèle prédit bien, et où nos coupons passent,
   sont mises en avant dans les coupons ; les autres sont reléguées.
"""
from __future__ import annotations

import numpy as np

import extra

BT_WEIGHT = 0.25
PRIOR_N = 100
MAX_SHIFT = 0.06


def build(backtest: dict | None, predictions: dict, coupon_store: dict) -> dict:
    sums = {}  # (div, market) -> [pred, obs, n]

    def add(div, mkt, pred, obs, w):
        s = sums.setdefault((div, mkt), [0.0, 0.0, 0.0])
        s[0] += pred * w
        s[1] += obs * w
        s[2] += w

    for lg in (backtest or {}).get("leagues", []):
        n = lg["n"] * BT_WEIGHT
        if "o15_pred" in lg:
            add(lg["div"], "o15", lg["o15_pred"], lg["o15_rate"], n)
        add(lg["div"], "o25", lg["o25_pred"], lg["o25_rate"], n)
    live_n = {}
    for e in predictions.values():
        if "goals" not in e:
            continue
        add(e["div"], "o15", e["o15"], float(e["goals"] >= 2), 1.0)
        add(e["div"], "o25", e["o25"], float(e["goals"] >= 3), 1.0)
        if e.get("fav_p") is not None and e.get("score"):
            hg, ag = map(int, e["score"].split("-"))
            add(e["div"], "fav", e["fav_p"], float(hg > ag if e["fav_side"] == "1" else ag > hg), 1.0)
        live_n[e["div"]] = live_n.get(e["div"], 0) + 1

    shifts = {}
    for (div, mkt), (p, o, n) in sums.items():
        shifts.setdefault(div, {})[mkt] = round(float(np.clip((o - p) / (n + PRIOR_N), -MAX_SHIFT, MAX_SHIFT)), 4)

    # Fiabilité : qualité du modèle sur le passé + réussite réelle des sélections jouées
    skills = {lg["div"]: lg.get("skill_o25", 0.0) for lg in (backtest or {}).get("leagues", [])}
    mean_skill = float(np.mean(list(skills.values()))) if skills else 0.0
    legs = {}
    for entry in coupon_store.values():
        for c in entry.get("coupons", []):
            for leg in c["legs"]:
                if leg.get("result") in ("won", "lost", "push"):
                    div = leg["id"].split("|")[1]
                    s = legs.setdefault(div, [0.0, 0.0, 0])
                    s[0] += leg["result"] != "lost"
                    s[1] += leg["p_win"] + leg["p_push"]
                    s[2] += 1
    rel = {}
    for div in set(skills) | set(legs):
        r = 1 + 2.0 * (skills.get(div, mean_skill) - mean_skill)
        if div in legs:
            won, pred, n = legs[div]
            r += float(np.clip((won - pred) / (n + 30), -0.15, 0.1))
        rel[div] = round(float(np.clip(r, 0.75, 1.2)), 3)
    # Par type de coupon : réussite réelle comparée à la probabilité annoncée
    kinds = {}
    for entry in coupon_store.values():
        for c in entry.get("coupons", []):
            if c.get("status") in ("won", "lost"):
                k = kinds.setdefault(c["kind"], [0, 0.0, 0])
                k[0] += c["status"] == "won"
                k[1] += c["p_win"]
                k[2] += 1
    kind_factor = {}
    for kind, (won, pred, n) in kinds.items():
        prior = 10 * (pred / n)
        kind_factor[kind] = {"n": n, "won": won, "pred": round(pred, 2),
                             "factor": round(float(np.clip((won + prior) / (pred + prior), 0.8, 1.2)), 3)}
    return {"shifts": shifts, "reliability": rel, "live_matches": live_n, "kinds": kind_factor}


def apply(pred_final: dict, div: str, fb: dict) -> dict:
    s = fb.get("shifts", {}).get(div, {})
    f = dict(pred_final)
    d15, d25 = s.get("o15", 0.0), s.get("o25", 0.0)
    push = f["o20_push"]
    f["o15"] = float(np.clip(f["o15"] + d15, 0.02, 0.99))
    f["o25"] = float(np.clip(f["o25"] + d25, 0.01, f["o15"] - 0.005))
    f["o20_win"] = f["o25"]
    f["o20_push"] = float(np.clip(f["o15"] - f["o25"], 0.0, 1.0)) if push is not None else 0.0
    f["o20"] = f["o25"] / max(1 - f["o20_push"], 1e-9)
    return f


GOAL_LABELS = {"o15": "+1,5 but", "o25": "+2,5 buts", "fav": "Victoire du favori"}
MAX_GAP = 0.02  # optimisme toléré sur le passé (annoncé au-dessus du réel)


def reliable_markets(backtest: dict | None, coupon_store: dict) -> list[dict]:
    """Marchés où l'appli est fiable : pas trop optimiste sur le passé, et le live ne passe pas sous le couloir.

    Sert à construire les jackpots fiables. Le live n'écarte un marché qu'avec au moins 30 sélections
    réglées et un écart plus grand que la marge due au hasard.
    """
    base = {}
    if backtest:
        for k in ("o15", "o25"):
            cal = (backtest.get("markets") or {}).get(k, {}).get("calibration") or []
            n = sum(c["n"] for c in cal)
            if n:
                base[k] = (n, sum(c["pred"] * c["n"] for c in cal) / n, sum(c["obs"] * c["n"] for c in cal) / n)
        fv = (backtest.get("coupons") or {}).get("favoris")
        for code, e in ((backtest.get("extra") or {}).get("markets") or {}).items():
            base[code] = (e["n"], e.get("pred_cal") or e["pred"], e["obs"])
        if fv:  # les tickets favoris rejoués : annoncé / réel sur des coupons entiers, plus exigeant qu'une sélection
            base["fav"] = (fv["n"], fv["pred_hit"], fv["hit"])
    live = {}
    seen = set()
    for e in coupon_store.values():
        for c in e.get("coupons", []):
            for l in c["legs"]:
                k = (l["id"], l["market"])
                if l.get("result") not in ("won", "lost") or k in seen:
                    continue
                seen.add(k)
                mk = "fav" if l["market"] in ("1", "2") else l["market"]
                s = live.setdefault(mk, [0, 0.0, 0])
                s[0] += 1; s[1] += l["p_win"]; s[2] += l["result"] == "won"
    out = []
    for mk, (n, pred, obs) in base.items():
        if mk in ("dnb1", "dnb2"):
            continue  # remboursement : pas adapté à un jackpot
        ok = obs - pred >= -MAX_GAP  # un réel au-dessus de l'annoncé ne pose pas de problème : seul l'optimisme écarte
        ln, lp, lw = live.get(mk, (0, 0.0, 0))
        live_gap = None
        if ln:
            lp, lo = lp / ln, lw / ln
            live_gap = round(lo - lp, 3)
            if ln >= 30 and lp - lo > 1.96 * np.sqrt(max(lp * (1 - lp), 1e-6) / ln):
                ok = False
        label = GOAL_LABELS.get(mk) or extra.LABELS.get(mk, (mk,))[0]
        out.append({"market": mk, "label": label, "n": n, "gap": round(obs - pred, 3), "live_n": ln, "live_gap": live_gap, "reliable": ok})
    return sorted(out, key=lambda x: (not x["reliable"], abs(x["gap"])))
