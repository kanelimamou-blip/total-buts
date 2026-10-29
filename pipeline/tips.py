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
