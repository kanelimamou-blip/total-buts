"""Astuces du jour, générées à partir des données."""
from __future__ import annotations

import pandas as pd

from config import COUPONS, LEAGUES


def _pct(x: float) -> str:
    return f"{x:g}".replace(".", ",") + " %"


def build(results: pd.DataFrame, matches: list[dict], season_start: pd.Timestamp, live: dict) -> list[dict]:
    tips = []
    season = results[results["date"] >= season_start]
    if len(season):
        g = season.assign(tot=season["hg"] + season["ag"]).groupby("div")["tot"]
        rates = g.apply(lambda t: (t >= 3).mean()).sort_values(ascending=False)
        counts = g.size()
        top = [d for d in rates.index if counts[d] >= 30][:1]
        low = [d for d in rates.index[::-1] if counts[d] >= 30][:1]
        if top:
            d = top[0]
            tips.append({"type": "ligue", "title": f"{LEAGUES[d][0]} : la ligue la plus prolifique",
                         "text": f"{rates[d] * 100:.0f} % des matchs de la saison ont fini avec 3 buts ou plus."})
        if low and low != top:
            d = low[0]
            tips.append({"type": "prudence", "title": f"Prudence sur le +2,5 en {LEAGUES[d][0]}",
                         "text": f"Seulement {rates[d] * 100:.0f} % des matchs à 3 buts ou plus cette saison. Préfère le +1,5."})

    upcoming = matches[:120]
    seen = set()
    hot, cold = [], []
    for m in upcoming:
        for side in ("home", "away"):
            team = m[side]
            f = m[f"form_{side}"]
            if team in seen or not f["games"] or len(f["games"]) < 6:
                continue
            seen.add(team)
            n3 = sum(g["gf"] + g["ga"] >= 3 for g in f["games"])
            if n3 >= 5:
                hot.append((n3, team, m))
            elif n3 <= 1:
                cold.append((n3, team, m))
    for n3, team, m in sorted(hot, key=lambda x: -x[0])[:3]:
        tips.append({"type": "equipe", "title": f"{team} en série de buts",
                     "text": f"{n3} de ses 6 derniers matchs avec 3 buts ou plus. Prochain : {m['home']} – {m['away']} ({m['league']}).",
                     "match": m["id"]})
    for n3, team, m in cold[:2]:
        tips.append({"type": "prudence", "title": f"{team} : matchs fermés",
                     "text": f"Seulement {n3} de ses 6 derniers matchs avec 3 buts ou plus. Évite le +2,5 sur {m['home']} – {m['away']}.",
                     "match": m["id"]})

    gaps = [m for m in upcoming if m["market_o25"] is not None]
    gaps.sort(key=lambda m: -(m["p"]["o25"] - m["market_o25"]))
    for m in gaps[:2]:
        diff = m["p"]["o25"] - m["market_o25"]
        if diff >= 0.04:
            tips.append({"type": "value", "title": f"Le modèle voit plus de buts que les bookmakers",
                         "text": f"{m['home']} – {m['away']} : {m['p']['o25'] * 100:.0f} % de +2,5 selon nous, {m['market_o25'] * 100:.0f} % selon le marché.",
                         "match": m["id"]})

    sur = live.get("sur")
    if sur and sur["n"] >= 5:
        tips.append({"type": "suivi", "title": "Nos coupons sûrs jusqu'ici",
                     "text": f"{sur['won']} gagnés sur {sur['n']}, bilan {sur['units']:+.2f} mise(s). Le modèle s'ajuste chaque jour sur ces résultats."})
    tips.append({"type": "discipline", "title": "Mise conseillée",
                 "text": f"{_pct(COUPONS['sur']['stake_pct'])} de ta bankroll sur un coupon sûr, {_pct(COUPONS['jackpot']['stake_pct'])} sur le jackpot. Des petits gains réguliers valent mieux qu'un gros coup."})
    tips.append({"type": "discipline", "title": "La cote minimum sur 1xBet",
                 "text": "Chaque sélection indique la cote minimum à exiger. Si 1xBet propose moins, remplace-la par une autre."})
    return tips


def surprises(results: pd.DataFrame, season_start: pd.Timestamp, min_games: int = 6) -> dict:
    """Équipes qui surprennent cette saison, mesurées contre les cotes d'avant-match :
    points gagnés au-delà (ou en deçà) de ce que les bookmakers prévoyaient, et matchs à +2,5 de plus ou de moins."""
    from model import devig, devig3
    season = results[results["date"] >= season_start]
    stats = {}
    for r in season.itertuples():
        p = devig3(r.oh, r.od, r.oa)
        q = devig(r.o25, r.u25)
        if p is None:
            continue
        tot = r.hg + r.ag
        for team, side, gf, ga in ((r.home, "1", r.hg, r.ag), (r.away, "2", r.ag, r.hg)):
            s = stats.setdefault((r.div, team), {"g": 0, "pts": 0.0, "xpts": 0.0, "o25": 0, "xo25": 0.0, "n25": 0})
            s["g"] += 1
            s["pts"] += 3 if gf > ga else (1 if gf == ga else 0)
            s["xpts"] += 3 * p[side] + p["X"]
            if q is not None:
                s["n25"] += 1
                s["o25"] += tot >= 3
                s["xo25"] += q
    rows = []
    for (div, team), s in stats.items():
        if s["g"] < min_games:
            continue
        rows.append({"team": team, "league": LEAGUES[div][0], "games": s["g"],
                     "pts": int(s["pts"]), "xpts": round(s["xpts"], 1), "diff": round((s["pts"] - s["xpts"]) / s["g"], 2),
                     "o25": s["o25"], "xo25": round(s["xo25"], 1), "n25": s["n25"],
                     "gdiff": round((s["o25"] - s["xo25"]) / max(s["n25"], 1), 2)})
    by = lambda k, rev: sorted(rows, key=lambda x: x[k], reverse=rev)[:10]
    return {"over": by("diff", True), "under": by("diff", False), "goals": by("gdiff", True), "closed": by("gdiff", False)}
