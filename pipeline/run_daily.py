"""Passage automatique : données -> modèle -> prédictions -> coupons -> suivi -> fichiers de l'appli.

Usage : python pipeline/run_daily.py [--offline] [--backtest] [--today AAAA-MM-JJ]
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

import backtest
import feedback
import tips as tips_mod
from config import COUPONS, LEAGUES, MARKETS, SITE_DATA, STATE_DIR
from coupons import build_day, legs_for_match, settle_coupon
from fetch import download, load_fixtures, load_results
from model import fit, predict

HORIZON_DAYS = 7


def match_id(d: pd.Timestamp, div: str, home: str, away: str) -> str:
    return f"{d.strftime('%Y%m%d')}|{div}|{home}|{away}"


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def team_form(results: pd.DataFrame, team: str, n: int = 6) -> dict:
    m = results[(results["home"] == team) | (results["away"] == team)].tail(n)
    games = []
    for r in m.itertuples():
        home = r.home == team
        games.append({"d": r.date.strftime("%d/%m"), "opp": r.away if home else r.home, "h": home,
                      "gf": int(r.hg if home else r.ag), "ga": int(r.ag if home else r.hg)})
    tot = [g["gf"] + g["ga"] for g in games]
    return {"games": games, "avg_total": round(float(np.mean(tot)), 2) if tot else None,
            "o25_rate": round(float(np.mean([t >= 3 for t in tot])), 2) if tot else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--today")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    today = date.fromisoformat(args.today) if args.today else now.date()
    ts_today = pd.Timestamp(today)

    if not args.offline:
        download(today)
    results = load_results()
    fixtures = load_fixtures()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SITE_DATA.mkdir(parents=True, exist_ok=True)

    bt = read_json(SITE_DATA / "backtest.json", None)
    stale = bt is None or (ts_today - pd.Timestamp(bt["generated"])).days >= 7
    if args.backtest or stale:
        print("Backtest…")
        backtest.run(results, today)
    blend = read_json(STATE_DIR / "model_config.json", {"blend": 0.6})["blend"]
    bt = read_json(SITE_DATA / "backtest.json", None)
    store = read_json(STATE_DIR / "coupons.json", {})
    log = read_json(STATE_DIR / "predictions.json", {})
    scores = {match_id(r.date, r.div, r.home, r.away): (int(r.hg), int(r.ag)) for r in results.itertuples()}
    for mid, e in log.items():
        if "goals" not in e and mid in scores:
            e["goals"] = sum(scores[mid])
            e["score"] = "%d-%d" % scores[mid]
    fb = feedback.build(bt, log, store)

    # Notes d'équipes et prédictions des matchs à venir
    fx = fixtures[(fixtures["date"] >= ts_today) & (fixtures["date"] < ts_today + pd.Timedelta(days=HORIZON_DAYS))]
    played = set(match_id(r.date, r.div, r.home, r.away) for r in results.itertuples())
    ratings, league_tables = {}, {}
    for div in LEAGUES:
        r = fit(results[results["div"] == div], ts_today)
        if r is not None:
            ratings[div] = r
            league_tables[div] = r.table()

    matches = []
    for row in fx.itertuples():
        r = ratings.get(row.div)
        mid = match_id(row.date, row.div, row.home, row.away)
        if r is None or mid in played:
            continue
        o25 = None if pd.isna(row.o25) else float(row.o25)
        u25 = None if pd.isna(row.u25) else float(row.u25)
        pr = predict(r, row.home, row.away, o25, u25, blend=blend)
        pr["final"] = feedback.apply(pr["final"], row.div, fb)
        mp = predict(r, row.home, row.away, o25, u25, blend=0.0)["final"] if pr["market_o25"] is not None else None
        legs = legs_for_match(pr, mp, o25)
        matches.append({
            "id": mid, "div": row.div, "league": LEAGUES[row.div][0], "country": LEAGUES[row.div][1],
            "date": row.date.strftime("%Y-%m-%d"), "time": row.time or "",
            "home": row.home, "away": row.away,
            "xg_home": pr["xg_home"], "xg_away": pr["xg_away"],
            "p": {"o15": round(pr["final"]["o15"], 3), "o20": round(pr["final"]["o20_win"], 3),
                  "o20_push": round(pr["final"]["o20_push"], 3), "o25": round(pr["final"]["o25"], 3)},
            "p_model": {"o15": round(pr["model"]["o15"], 3), "o25": round(pr["model"]["o25"], 3)},
            "market_o25": None if pr["market_o25"] is None else round(pr["market_o25"], 3),
            "odds_o25": o25,
            "legs": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in l.items()} for l in legs],
            "top_scores": pr["top_scores"], "total_dist": pr["total_dist"],
            "form_home": team_form(results, row.home), "form_away": team_form(results, row.away),
        })
    matches.sort(key=lambda m: (m["date"], m["time"], -m["p"]["o15"]))

    # Coupons : le jour J est figé au premier passage du jour, J+1 et J+2 restent provisoires
    by_date = {}
    for m in matches:
        by_date.setdefault(m["date"], []).append(m)
    for d in sorted(by_date):
        if d > (today + timedelta(days=2)).isoformat():
            continue
        if d in store and store[d].get("frozen"):
            continue
        day = [{"id": m["id"], "div": m["div"], "rel": fb["reliability"].get(m["div"], 1.0), "legs": m["legs"]} for m in by_date[d]]
        coupons = build_day(day, league_names={k: v[0] for k, v in LEAGUES.items()})
        store[d] = {"frozen": d == today.isoformat(), "created": now.isoformat(timespec="minutes"), "coupons": coupons}

    # Règlement des coupons passés
    for d, entry in store.items():
        for c in entry["coupons"]:
            if c.get("status") in ("won", "lost", "void"):
                continue
            if settle_coupon(c, scores) is None and d < (today - timedelta(days=6)).isoformat():
                c["status"] = "void"  # match reporté ou introuvable
    (STATE_DIR / "coupons.json").write_text(json.dumps(store, ensure_ascii=False, indent=1))

    # Journal des prédictions (pour mesurer la fiabilité en conditions réelles)
    # la dernière prédiction avant le match fait foi
    for m in matches:
        log[m["id"]] = {"date": m["date"], "div": m["div"], "home": m["home"], "away": m["away"],
                        "o15": m["p"]["o15"], "o25": m["p"]["o25"]}
    (STATE_DIR / "predictions.json").write_text(json.dumps(log, indent=0))

    # Statistiques réelles
    live = {}
    for kind in COUPONS:
        done = [c for e in store.values() for c in e["coupons"] if c["kind"] == kind and c.get("status") in ("won", "lost")]
        if done:
            live[kind] = {"n": len(done), "won": sum(c["status"] == "won" for c in done),
                          "units": round(sum(c["return"] - 1 for c in done), 2)}
    settled = [e for e in log.values() if "goals" in e]
    pred_stats = None
    if settled:
        p15 = np.array([e["o15"] for e in settled]); y15 = np.array([e["goals"] >= 2 for e in settled])
        p25 = np.array([e["o25"] for e in settled]); y25 = np.array([e["goals"] >= 3 for e in settled])
        pred_stats = {"n": len(settled), "o15_pred": round(float(p15.mean()), 3), "o15_obs": round(float(y15.mean()), 3),
                      "o25_pred": round(float(p25.mean()), 3), "o25_obs": round(float(y25.mean()), 3)}

    season_start = pd.Timestamp(year=today.year if today.month >= 7 else today.year - 1, month=7, day=1)
    tip_list = tips_mod.build(results, matches, season_start, live)

    # Derniers résultats de nos prédictions (journal), pour l'écran Suivi
    recent = sorted(((mid, e) for mid, e in log.items() if "goals" in e), key=lambda x: x[1]["date"], reverse=True)[:80]
    recent_out = [{"id": mid, "date": e["date"], "league": LEAGUES[e["div"]][0], "home": e.get("home", mid.split("|")[2]),
                   "away": e.get("away", mid.split("|")[3]), "score": e.get("score"), "goals": e["goals"],
                   "o15": e["o15"], "o25": e["o25"]} for mid, e in recent]

    match_index = {m["id"]: m for m in matches}
    history = []
    for d in sorted(store, reverse=True)[:60]:
        for c in store[d]["coupons"]:
            history.append(dict(c, date=d, frozen=store[d].get("frozen", False)))
    # infos de match lisibles pour les coupons passés
    def describe(mid):
        _, div, home, away = mid.split("|")
        m = match_index.get(mid)
        if m:
            return {"home": m["home"], "away": m["away"], "league": m["league"], "time": m["time"]}
        return {"home": home, "away": away, "league": LEAGUES.get(div, (div,))[0], "time": ""}
    for c in history:
        for leg in c["legs"]:
            leg.update({k: v for k, v in describe(leg["id"]).items() if k not in leg})

    out = {
        "generated": now.isoformat(timespec="minutes"), "today": today.isoformat(), "blend": blend,
        "markets": MARKETS, "coupon_kinds": COUPONS,
        "leagues": {d: {"name": n, "country": c} for d, (n, c) in LEAGUES.items()},
        "matches": matches, "coupons": history, "live": live, "predictions": pred_stats,
        "tips": tip_list, "recent": recent_out, "feedback": fb,
        "last_result_date": results["date"].max().strftime("%Y-%m-%d") if len(results) else None,
    }
    (SITE_DATA / "app.json").write_text(json.dumps(out, ensure_ascii=False))
    (SITE_DATA / "teams.json").write_text(json.dumps(league_tables, ensure_ascii=False))
    print(f"{len(matches)} matchs à venir, {sum(len(e['coupons']) for e in store.values())} coupons en mémoire.")


if __name__ == "__main__":
    main()
