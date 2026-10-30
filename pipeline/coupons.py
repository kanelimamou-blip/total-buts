"""Construction des coupons à partir des sélections d'une journée.

Chaque sélection (leg) a : p_win, p_push (remboursé, seulement pour +2), odds (cote estimée).
Pour un coupon, on maximise la probabilité de ne pas perdre, sous contrainte que la cote
espérée quand on ne perd pas atteigne la cible.
"""
from __future__ import annotations

from itertools import combinations, product

import numpy as np

from config import BOOK_MARGIN, COUPONS, MAX_PER_DAY, MIN_LEG_ODDS, MIN_P, VALUE_EDGE
from model import fair_odds

MKT_ORDER = ["o15", "o20", "o25"]


def legs_for_match(pred: dict, market_pred: dict | None, real_o25: float | None) -> list[dict]:
    """Sélections possibles d'un match avec cote estimée du bookmaker.

    market_pred : probabilités issues du marché seul (None si pas de cotes).
    """
    f = pred["final"]
    out = []
    for m in MKT_ORDER:
        p_win = f["o20_win"] if m == "o20" else f[m]
        p_push = f["o20_push"] if m == "o20" else 0.0
        if m == "o25" and real_o25 and real_o25 > 1:
            odds, source = float(real_o25), "marché"
        else:
            ref = market_pred if market_pred is not None else pred["model"]
            odds, source = max(fair_odds(m, ref) / (1 + BOOK_MARGIN), 1.05), "estimée"  # 1,05 : plus petite cote proposée en pratique
        fair = fair_odds(m, f)
        out.append({
            "market": m, "p_win": p_win, "p_push": p_push, "p_lose": 1 - p_win - p_push,
            "odds": round(max(odds, 1.01), 2), "odds_source": source,
            "fair": round(fair, 2), "min_odds": round(fair * (1 + VALUE_EDGE), 2),
            "ev": p_win * odds + p_push - 1,
        })
    return out


def _leg_stats(leg):
    p_ok = leg["p_win"] + leg["p_push"]
    cond_odds = (leg["p_win"] * leg["odds"] + leg["p_push"]) / max(p_ok, 1e-9)
    return np.log(max(p_ok, 1e-12)), np.log(cond_odds)


def _search(matches: list[dict], k_range, min_odds, allowed, pool, score="safety", max_odds=1e9, max_o25=1, mk_order=None):
    """matches : [{"id":..., "legs":[...]}]. Recherche exhaustive vectorisée."""
    if len(matches) < k_range[0]:
        return None
    mk = [m for m in (mk_order or MKT_ORDER) if m in allowed]
    pool_matches = sorted(matches, key=lambda m: -max((l["p_win"] + l["p_push"] for l in m["legs"] if l["market"] in mk), default=0))[:pool]
    n = len(pool_matches)
    lp = np.full((n, len(mk)), -np.inf)
    lr = np.array([0.5 * np.log(m.get("rel", 1.0)) for m in pool_matches])
    lo = np.zeros((n, len(mk)))
    ev = np.full((n, len(mk)), -1.0)
    no = np.zeros((n, len(mk)))
    for i, m in enumerate(pool_matches):
        for j, name in enumerate(mk):
            leg = next((l for l in m["legs"] if l["market"] == name), None)
            if leg is None or leg.get("excluded") or leg["odds"] < MIN_LEG_ODDS:
                continue
            lp[i, j], lo[i, j] = _leg_stats(leg)
            ev[i, j] = leg["ev"]
            no[i, j] = np.log(leg["odds"])
    best = None
    for k in range(k_range[0], k_range[1] + 1):
        if n < k:
            break
        C = np.array(list(combinations(range(n), k)))
        M = np.array(list(product(range(len(mk)), repeat=k)))
        if "o25" in mk:  # le cœur du coupon reste sur +1,5 / +2 : au plus max_o25 sélections à +2,5
            M = M[(M == mk.index("o25")).sum(1) <= max_o25]
        P = lp[C[:, None, :], M[None, :, :]].sum(-1)
        O = lo[C[:, None, :], M[None, :, :]].sum(-1)
        NO = no[C[:, None, :], M[None, :, :]].sum(-1)
        ok = (O >= np.log(min_odds)) & (NO <= np.log(max_odds)) & np.isfinite(P)
        if not ok.any():
            continue
        R = lr[C].sum(-1)[:, None]
        if score == "ev":
            S = np.where(ok, P + O + R, -np.inf)
        else:
            S = np.where(ok, P + R - 0.15 * (O - np.log(min_odds)), -np.inf)  # légère préférence pour rester proche de la cible
        ci, mi = np.unravel_index(np.argmax(S), S.shape)
        cand = (S[ci, mi], P[ci, mi], O[ci, mi], [(pool_matches[c], mk[mm]) for c, mm in zip(C[ci], M[mi])])
        # à score proche, préférer moins de sélections
        if best is None or cand[0] > best[0] + 0.02:
            best = cand
    if best is None:
        return None
    _, p, o, picks = best
    return p, o, picks


def _pack(kind, p_log, o_log, picks, scope="Toutes ligues"):
    cfg = COUPONS[kind]
    legs = []
    nominal = 1.0
    p_full = 1.0
    rel = []
    for m, name in picks:
        leg = next((l for l in m["legs"] if l["market"] == name), None) or m.get("fav")
        nominal *= leg["odds"]
        p_full *= leg["p_win"]
        rel.append(m.get("rel", 1.0))
        legs.append({"id": m["id"], "market": name, "team": leg.get("team"), "odds": leg["odds"], "odds_source": leg["odds_source"],
                     "p_win": round(leg["p_win"], 3), "p_push": round(leg["p_push"], 3), "min_odds": leg["min_odds"]})
    p_ok = float(np.exp(p_log))
    exp_odds = float(np.exp(o_log))
    return {
        "kind": kind, "label": cfg["label"], "scope": scope, "stake_pct": cfg["stake_pct"],
        "legs": legs, "odds": round(nominal, 2), "p_win": round(p_full, 3),
        "p_not_lose": round(p_ok, 3), "ev": round(p_ok * exp_odds - 1, 3),
        "reliability": round(float(np.mean(rel)), 3),
    }


def _repeat(kind, matches, allowed, pool, score="safety", scope="Toutes ligues", max_o25=1, mk_order=None):
    """Construit autant de coupons que possible tant qu'ils passent le seuil de probabilité."""
    cfg = COUPONS[kind]
    out, rest = [], list(matches)
    while len(out) < MAX_PER_DAY[kind]:
        r = _search(rest, cfg["legs"], cfg["min_odds"], allowed, pool=pool, score=score, max_odds=cfg["max_odds"], max_o25=max_o25, mk_order=mk_order)
        if not r or np.exp(r[0]) < MIN_P[kind]:
            break
        out.append(_pack(kind, *r, scope=scope))
        ids = {m["id"] for m, _ in r[2]}
        rest = [m for m in rest if m["id"] not in ids]
    return out


def build_day(matches: list[dict], kinds=("sur", "ligue", "favoris", "value", "audace", "jackpot"), league_names=None) -> list[dict]:
    """Coupons d'une journée. matches : [{"id", "div", "rel", "legs"}].

    Les coupons sûrs toutes ligues ne partagent aucun match entre eux ; les coupons par championnat
    sont une alternative (ils peuvent reprendre les mêmes matchs), à toi de choisir.
    """
    out = []
    if "sur" in kinds:
        out += _repeat("sur", matches, {"o15", "o20", "o25"}, pool=12)
    if "ligue" in kinds:
        by_div = {}
        for m in matches:
            by_div.setdefault(m.get("div"), []).append(m)
        for div, ms in by_div.items():
            if len(ms) >= COUPONS["ligue"]["legs"][0]:
                name = (league_names or {}).get(div, div)
                out += _repeat("ligue", ms, {"o15", "o20", "o25"}, pool=10, scope=name)[:1]
    if "favoris" in kinds:
        out += build_favorites(matches)
    if "value" in kinds:
        vm = []
        for m in matches:
            legs = [dict(l, excluded=(l["ev"] < VALUE_EDGE)) for l in m["legs"]]
            if any(not l["excluded"] for l in legs):
                vm.append(dict(m, legs=legs))
        out += _repeat("value", vm, {"o15", "o20", "o25"}, pool=10, score="ev")
    if "audace" in kinds:
        out += _repeat("audace", matches, {"o15", "o20", "o25"}, pool=9, max_o25=2)
    if "jackpot" in kinds:
        # Jackpot : base en +2 sur les matchs les plus sûrs, puis passage de quelques sélections en +2,5
        cfg = COUPONS["jackpot"]

        def leg(m, mk):
            return next(l for l in m["legs"] if l["market"] == mk)

        ranked = [m for m in sorted(matches, key=lambda m: -(leg(m, "o20")["p_win"] + leg(m, "o20")["p_push"]) * m.get("rel", 1))
                  if leg(m, "o20")["odds"] >= MIN_LEG_ODDS][:cfg["legs"][1]]
        if len(ranked) >= cfg["legs"][0]:
            picks = [[m, "o20"] for m in ranked]
            odds = lambda: float(np.prod([leg(m, mk)["odds"] for m, mk in picks]))
            upgrades = sorted(range(len(picks)), key=lambda i: -leg(picks[i][0], "o25")["p_win"])
            for i in upgrades:
                if odds() >= cfg["min_odds"]:
                    break
                picks[i][1] = "o25"
            if odds() >= cfg["min_odds"]:
                stats = [_leg_stats(leg(m, mk)) for m, mk in picks]
                out.append(_pack("jackpot", sum(s[0] for s in stats), sum(s[1] for s in stats), [tuple(p) for p in picks]))
    return prioritise(out)


def prioritise(coupons: list[dict]) -> list[dict]:
    """Classe les coupons du jour : probabilité, fiabilité des championnats et valeur. Le jackpot reste en dernier."""
    def score(c):
        if c["kind"] in ("jackpot", "mille"):
            return -1.0 if c["kind"] == "jackpot" else -2.0
        return c["p_not_lose"] * c["reliability"] * (1 + max(min(c["ev"], 0.2), -0.15))
    coupons.sort(key=score, reverse=True)
    n = len(coupons)
    for i, c in enumerate(coupons):
        c["priority"] = i + 1
        c["level"] = "haute" if c["kind"] not in ("jackpot", "mille") and i < max(1, n // 3) else ("basse" if c["kind"] in ("jackpot", "audace", "mille") or i >= 2 * n // 3 else "moyenne")
    return coupons


def favorite_leg(pred: dict, home: str, away: str, odds_1x2=None) -> dict:
    """Sélection « victoire du favori » : l'équipe la plus probable de gagner."""
    res = pred["res"]
    side = "1" if res["1"] >= res["2"] else "2"
    p = res[side]
    real = None
    if odds_1x2:
        try:
            real = float(odds_1x2[0 if side == "1" else 2])
            real = real if real > 1 else None
        except (TypeError, ValueError):
            real = None
        if real is not None and np.isnan(real):
            real = None
    odds = real if real else max((1 / max(p, 1e-9)) / (1 + BOOK_MARGIN), 1.05)
    return {"market": side, "team": home if side == "1" else away, "p_win": p, "p_push": 0.0, "p_lose": 1 - p,
            "odds": round(max(odds, 1.01), 2), "odds_source": "marché" if real else "estimée",
            "fair": round(1 / max(p, 1e-9), 2), "min_odds": round((1 / max(p, 1e-9)) * (1 + VALUE_EDGE), 2),
            "ev": p * odds - 1}


def build_favorites(matches: list[dict], kind="favoris", scope="Toutes ligues", min_p_leg=0.6) -> list[dict]:
    """Tickets de favoris : 3 à 4 victoires de favoris nets, sans doublon de match entre tickets."""
    fav = [{"id": m["id"], "div": m.get("div"), "rel": m.get("rel", 1.0), "legs": [m["fav"]]}
           for m in matches if m.get("fav") and m["fav"]["p_win"] >= min_p_leg]
    return _repeat(kind, fav, {"1", "2"}, pool=12, scope=scope, mk_order=["1", "2"])


def build_mille(matches: list[dict]) -> dict | None:
    """Ticket « cote 1000 » : atteindre 1000 en perdant le moins de probabilité possible.

    Pour chaque match on garde la sélection qui apporte le plus de cote par unité de risque
    (log cote / -log probabilité), puis on empile les meilleures jusqu'à 1000.
    """
    cfg = COUPONS["mille"]
    cands = []
    for m in matches:
        opts = [l for l in m["legs"] if l["market"] in ("o15", "o25") and l["odds"] >= 1.2]
        if m.get("fav") and m["fav"]["odds"] >= 1.2:
            opts.append(m["fav"])
        best = None
        for l in opts:
            eff = np.log(l["odds"]) / max(-np.log(max(l["p_win"], 1e-6)), 1e-6)
            if best is None or eff > best[0]:
                best = (eff, l)
        if best:
            cands.append((best[0], m, best[1]))
    cands.sort(key=lambda x: -x[0])
    picks, odds, p_log = [], 1.0, 0.0
    for _, m, l in cands[:cfg["legs"][1]]:
        picks.append((m, l["market"]))
        odds *= l["odds"]
        p_log += np.log(l["p_win"])
        if odds >= cfg["min_odds"]:
            break
    if odds < cfg["min_odds"] or len(picks) < cfg["legs"][0]:
        return None
    return _pack("mille", p_log, np.log(odds), picks)


def settle_leg(market: str, total: int, hg: int = 0, ag: int = 0) -> str:
    if market == "1":
        return "won" if hg > ag else "lost"
    if market == "2":
        return "won" if ag > hg else "lost"
    if market == "o15":
        return "won" if total >= 2 else "lost"
    if market == "o25":
        return "won" if total >= 3 else "lost"
    return "won" if total >= 3 else ("push" if total == 2 else "lost")


def settle_coupon(coupon: dict, scores: dict) -> dict | None:
    """scores : id du match -> (buts domicile, buts extérieur). Renvoie None si un match n'est pas encore joué."""
    payout = 1.0
    status = "won"
    for leg in coupon["legs"]:
        if leg["id"] not in scores:
            return None
    for leg in coupon["legs"]:
        hg, ag = scores[leg["id"]]
        r = settle_leg(leg["market"], hg + ag, hg, ag)
        leg["result"] = r
        leg["goals"] = int(hg + ag)
        leg["score"] = f"{int(hg)}-{int(ag)}"
        if r == "lost":
            status = "lost"
        elif r == "won":
            payout *= leg["odds"]
    coupon["status"] = status
    coupon["return"] = round(payout if status == "won" else 0.0, 3)
    return coupon
