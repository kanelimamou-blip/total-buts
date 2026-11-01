"""Paris live : propositions sur les matchs du jour en cours, recalculées avec le score et la minute.

Au passage horaire, chaque match en cours reçoit une proposition figée (minute, score, chance, cote minimale),
réglée ensuite sur le score final et suivie comme les autres coupons. L'appli recalcule aussi en temps réel
sur le téléphone, mais seule la proposition figée est suivie (sinon on ne mesurerait que ce qui arrange).

Modèle : les buts restants suivent une loi de Poisson, au rythme d'avant-match (xG) réduit au temps restant.
Les cartons rouges, le jeu réel et les changements ne sont pas pris en compte : c'est dit dans l'appli.
"""
from __future__ import annotations

from datetime import date

import numpy as np
from scipy.stats import poisson

import europe

LIVE_MARGIN = 0.08      # marge estimée des bookmakers en live (plus forte qu'avant-match)
MIN_P, MAX_P = 0.62, 0.95   # au-dessus de 95 %, la cote live est trop basse pour valoir le coup
FULL = 94
MIN_LIVE_ODDS = 1.25                # durée moyenne d'un match, temps additionnel compris


def now(slugs: list[str], today: date) -> dict:
    """espn_id -> (buts dom., buts ext., minute) pour les matchs en cours."""
    out = {}
    for slug in slugs:
        rows = europe._fetch(slug, today, 1) or []
        for r in rows:
            if r.get("state") == "in" and r.get("hg") is not None:
                out[str(r["espn_id"])] = (r["hg"], r["ag"], r.get("minute") or 0)
    return out


def probs(xg_h: float, xg_a: float, hg: int, ag: int, minute: int) -> dict:
    """Probabilités (fin du match) des marchés suivis, sachant le score et la minute."""
    rem = max(0.0, FULL - min(minute, FULL - 1)) / FULL
    lh, la = xg_h * rem, xg_a * rem
    k = np.arange(0, 11)
    ph, pa = poisson.pmf(k, lh), poisson.pmf(k, la)
    mat = np.outer(ph, pa)                       # buts restants dom. x ext.
    H = np.broadcast_to(hg + k[:, None], mat.shape)  # score final
    A = np.broadcast_to(ag + k[None, :], mat.shape)
    T = H + A
    p = lambda mask: float(mat[mask].sum())
    out = {"o15": p(T >= 2), "o25": p(T >= 3), "u35": p(T <= 3), "u45": p(T <= 4),
           "1": p(H > A), "2": p(A > H), "1X": p(H >= A), "X2": p(A >= H),
           "h05": p(H >= 1), "a05": p(A >= 1), "h15": p(H >= 2), "a15": p(A >= 2)}
    return out


def proposal(m: dict, hg: int, ag: int, minute: int) -> dict | None:
    """La sélection live la plus sûre dont la cote estimée atteint 1,25."""
    pr = probs(m["xg_home"], m["xg_away"], hg, ag, minute)
    fav = "1" if m["res"]["1"] >= m["res"]["2"] else "2"
    # pas de +2,5 dans les coupons (règle d'Est du 31/10/2026)
    allowed = ["o15", "u35", "u45", fav, "1X" if fav == "1" else "X2", "h05" if fav == "1" else "a05",
               "h15" if fav == "1" else "a15"]
    best = None
    for mk in allowed:
        q = pr[mk]
        odds = (1 / q) / (1 + LIVE_MARGIN)
        # la plus forte chance dont la cote live vaut encore le coup (1,25 au moins)
        if MIN_P <= q <= MAX_P and odds >= MIN_LIVE_ODDS and (best is None or q > best[0]):
            best = (q, mk, q)
    if not best:
        return None
    _, mk, q = best
    fair = 1 / q
    return {"id": m["id"], "market": mk, "team": m["home"] if mk in ("1", "h05", "h15") else m["away"] if mk in ("2", "a05", "a15") else None,
            "odds": round(max(fair / (1 + LIVE_MARGIN), 1.05), 2), "odds_source": "estimée", "p_win": round(q, 3), "p_push": 0.0,
            "min_odds": round(fair * 1.03, 2), "live_minute": int(minute), "live_score": f"{hg}-{ag}"}


def build(matches: list[dict], live_now: dict, already: set) -> list[dict]:
    """Coupons live à cote 2 au moins : la sélection la plus sûre de chaque match en cours, regroupées
    de la plus sûre à la moins sûre jusqu'à la cote 2 (2 à 4 matchs). Un match n'entre que dans un coupon live."""
    legs = []
    for m in matches:
        ref = m.get("espn")
        if not ref or m["id"] in already or m.get("provisional"):
            continue
        st = live_now.get(str(ref[1]))
        if not st or st[2] >= 80:
            continue
        leg = proposal(m, *st)
        if leg:
            legs.append(leg)
    legs.sort(key=lambda l: -l["p_win"])
    out, cur, o = [], [], 1.0
    for leg in legs:
        cur.append(leg)
        o *= leg["odds"]
        if o >= 2.0:
            out.append(_coupon(cur, o))
            cur, o = [], 1.0
        elif len(cur) == 4:
            cur, o = [], 1.0
    return out


def _coupon(picks: list[dict], o: float) -> dict:
    pw = float(np.prod([l["p_win"] for l in picks]))
    return {"kind": "live_combi", "label": "Coupon live", "scope": f"{len(picks)} matchs en cours", "stake_pct": 0.5,
            "legs": [dict(l) for l in picks], "odds": round(o, 2), "p_win": round(pw, 3), "p_not_lose": round(pw, 3),
            "ev": round(pw * (1 + (o - 1) * 0.8) - 1, 3), "reliability": 1.0}
