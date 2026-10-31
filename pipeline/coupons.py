"""Construction des coupons à partir des sélections d'une journée.

Chaque sélection (leg) a : p_win, p_push (remboursé, seulement pour +2), odds (cote estimée).
Pour un coupon, on maximise la probabilité de ne pas perdre, sous contrainte que la cote
espérée quand on ne perd pas atteigne la cible.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations, product

import numpy as np

from config import BOOK_MARGIN, COUPON_EXCLUDED, COUPONS, MAX_COUPONS_PER_MATCH, MAX_PER_DAY, MIN_LEG_ODDS, MIN_LEG_P, MIN_P, TAX, VALUE_EDGE
import extra
from model import fair_odds

MKT_ORDER = ["o15", "o20", "o25"]
EXTRA_ORDER = ["u45", "1X", "X2", "h05", "a05", "sh05", "dnb1", "dnb2", "ht05", "u35", "h15", "a15"]


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


def _search(matches: list[dict], k_range, min_odds, allowed, pool, score="safety", max_odds=1e9, max_o25=1, mk_order=None, min_leg_p=0.0, mix=False):
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
            if (leg is None or leg.get("excluded") or leg["odds"] < MIN_LEG_ODDS or leg["p_win"] + leg["p_push"] < min_leg_p
                    or leg.get("side", leg["market"]) in COUPON_EXCLUDED):
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
        if mix and "fav" in mk:  # coupon mix : au moins une victoire de favori et au moins une sélection de buts
            nf = (M == mk.index("fav")).sum(1)
            M = M[(nf >= 1) & (nf < k)]
        if not len(M):
            continue
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
        legs.append({"id": m["id"], "market": leg.get("side", name), "team": leg.get("team"), "odds": leg["odds"], "odds_source": leg["odds_source"],
                     "p_win": round(leg["p_win"], 3), "p_push": round(leg["p_push"], 3), "min_odds": leg["min_odds"]})
    p_ok = float(np.exp(p_log))
    exp_odds = float(np.exp(o_log))
    return {
        "kind": kind, "label": cfg["label"], "scope": scope, "stake_pct": cfg["stake_pct"],
        "legs": legs, "odds": round(nominal, 2), "p_win": round(p_full, 3),
        "p_not_lose": round(p_ok, 3), "ev": round(p_ok * (1 + (exp_odds - 1) * (1 - TAX)) - 1, 3),  # après taxe
        "reliability": round(float(np.mean(rel)), 3),
    }


def _repeat(kind, matches, allowed, pool, score="safety", scope="Toutes ligues", max_o25=1, mk_order=None, mix=False):
    """Construit autant de coupons que possible tant qu'ils passent le seuil de probabilité."""
    cfg = COUPONS[kind]
    out, rest = [], list(matches)
    while len(out) < MAX_PER_DAY[kind]:
        r = _search(rest, cfg["legs"], cfg["min_odds"], allowed, pool=pool, score=score, max_odds=cfg["max_odds"], max_o25=max_o25,
                    mk_order=mk_order, min_leg_p=MIN_LEG_P.get(kind, 0.0), mix=mix)
        if not r or np.exp(r[0]) < MIN_P[kind]:
            break
        out.append(_pack(kind, *r, scope=scope))
        ids = {m["id"] for m, _ in r[2]}
        rest = [m for m in rest if m["id"] not in ids]
    return out


def _virtual(matches: list[dict], markets: set) -> list[dict]:
    """Garde pour chaque match ses 2 meilleures sélections parmi `markets` (la plus sûre et la plus
    rentable en cote par unité de risque), renommées x1 / x2 : la recherche reste rapide malgré
    le grand nombre de marchés. Le vrai marché est conservé dans « side »."""
    out = []
    for m in matches:
        c = [l for l in m["legs"] if l["market"] in markets and not l.get("excluded") and l["odds"] >= MIN_LEG_ODDS]
        if not c:
            continue
        safe = max(c, key=lambda l: l["p_win"] + l["p_push"])
        eff = max(c, key=lambda l: np.log(l["odds"]) / max(-np.log(max(l["p_win"] + l["p_push"], 1e-6)), 1e-6))
        legs = [dict(safe, market="x1", side=safe["market"])]
        if eff is not safe:
            legs.append(dict(eff, market="x2", side=eff["market"]))
        out.append(dict(m, legs=legs))
    return out


def build_day(matches: list[dict], kinds=("sur", "favoris", "buts15", "buts20", "mix", "dc", "autres", "ligue", "value", "audace", "jackpot",
                                          "jackpot_fiable"),
              league_names=None) -> list[dict]:
    """Coupons d'une journée. matches : [{"id", "div", "rel", "legs"}].

    Les coupons sûrs toutes ligues ne partagent aucun match entre eux ; les coupons par championnat
    peuvent reprendre ces matchs, mais un match ne figure jamais dans plus de MAX_COUPONS_PER_MATCH coupons.
    """
    out = []
    uses, used_mk = Counter(), {}

    def add(cs):  # exposition de chaque match et sélections déjà prises
        for c in cs:
            for l in c["legs"]:
                uses[l["id"]] += 1
                used_mk.setdefault(l["id"], set()).add(l["market"])
        out.extend(cs)

    def free(ms):
        """Matchs encore disponibles, sans les sélections déjà jouées ailleurs : seuls d'autres marchés, qui protègent, restent."""
        res = []
        for m in ms:
            if uses[m["id"]] >= MAX_COUPONS_PER_MATCH:
                continue
            taken = used_mk.get(m["id"], set())
            legs = [dict(l, excluded=True) if l.get("side", l["market"]) in taken else l for l in m["legs"]]
            fav = m.get("fav")
            res.append(dict(m, legs=legs, fav=None if fav and fav["market"] in taken else fav))
        return res

    if "sur" in kinds:
        add(_repeat("sur", matches, {"o15", "o20", "o25"}, pool=12))
    if "favoris" in kinds:
        add(build_favorites(free(matches)))
    if "buts15" in kinds:
        add(_repeat("buts15", free(matches), {"o15"}, pool=14))
    if "buts20" in kinds:
        add(_repeat("buts20", free(matches), {"o20"}, pool=12))
    if "mix" in kinds:
        mm = [dict(m, legs=m["legs"] + [dict(m["fav"], market="fav", side=m["fav"]["market"])]) for m in free(matches) if m.get("fav")]
        add(_repeat("mix", mm, {"o15", "o20", "o25", "fav"}, pool=12, mk_order=["o15", "o20", "o25", "fav"], mix=True))
    if "ligue" in kinds:
        by_div = {}
        for m in matches:
            by_div.setdefault(m.get("div"), []).append(m)
        for div, ms in by_div.items():
            ms = free(ms)
            if len(ms) >= COUPONS["ligue"]["legs"][0]:
                name = (league_names or {}).get(div, div)
                add(_repeat("ligue", ms, {"o15", "o20", "o25"}, pool=10, scope=name)[:1])
    if "dc" in kinds:  # double chance et remboursé si nul : le favori ne doit pas perdre
        add(_repeat("dc", _virtual(free(matches), {"1X", "X2", "dnb1", "dnb2"}), {"x1", "x2"}, pool=12, mk_order=["x1", "x2"]))
    if "autres" in kinds:
        add(_repeat("autres", _virtual(free(matches), set(EXTRA_ORDER)), {"x1", "x2"}, pool=12, mk_order=["x1", "x2"]))
    if "value" in kinds:
        vm = []
        for m in free(matches):
            legs = [dict(l, excluded=(l["ev"] < VALUE_EDGE)) for l in m["legs"]]
            if any(not l["excluded"] for l in legs):
                vm.append(dict(m, legs=legs))
        add(_repeat("value", vm, {"o15", "o20", "o25"}, pool=10, score="ev"))
    if "audace" in kinds:
        add(_repeat("audace", free(matches), {"o15", "o20", "o25"}, pool=9, max_o25=2))
    if "jackpot_fiable" in kinds:
        out.extend(build_jackpots(matches))
    if "jackpot" in kinds:
        # Jackpot : uniquement des +2 (remboursés à 2 buts) sur les matchs les plus sûrs, jusqu'à la cote visée
        cfg = COUPONS["jackpot"]

        def leg(m, mk):
            return next(l for l in m["legs"] if l["market"] == mk)

        ranked = [m for m in sorted(matches, key=lambda m: -(leg(m, "o20")["p_win"] + leg(m, "o20")["p_push"]) * m.get("rel", 1))
                  if leg(m, "o20")["odds"] >= MIN_LEG_ODDS][:cfg["legs"][1]]
        if len(ranked) >= cfg["legs"][0]:
            picks, o = [], 1.0
            for m in ranked:
                picks.append([m, "o20"])
                o *= leg(m, "o20")["odds"]
                if o >= cfg["min_odds"] and len(picks) >= cfg["legs"][0]:
                    break
            if o >= cfg["min_odds"]:
                stats = [_leg_stats(leg(m, mk)) for m, mk in picks]
                out.append(_pack("jackpot", sum(s[0] for s in stats), sum(s[1] for s in stats), [tuple(p) for p in picks]))
    return prioritise(out)


KIND_FACTOR: dict = {}  # rempli chaque jour par le retour d'expérience (feedback.build)


# Coupons « à jouer » : 2-3 matchs (parfois plus), cote 2 au moins, suivis par combinaison
SMALL_KINDS = {"sur", "ligue", "favoris", "buts15", "buts20", "mix", "dc", "autres", "value", "tendance"}
COMBO_FACTOR: dict = {}  # signature -> facteur, rempli chaque jour (feedback.combo_factors)


def leg_family(market: str) -> str:
    if market in ("o15", "o20", "o25"):
        return "buts"
    if market in ("1", "2"):
        return "favori"
    if market in ("1X", "X2", "dnb1", "dnb2"):
        return "double chance"
    if market in ("u35", "u45"):
        return "moins de buts"
    return "autres"


def signature(c: dict) -> str:
    """Type de combinaison d'un coupon : nombre de matchs et familles de paris, ex. « 2 matchs · buts + favori »."""
    n = len(c["legs"])
    fams = sorted({leg_family(l["market"]) for l in c["legs"]})
    return f"{n if n <= 4 else '5+'} matchs · {' + '.join(fams)}"


def prioritise(coupons: list[dict]) -> list[dict]:
    """Classe les coupons du jour : probabilité, fiabilité des championnats et valeur. Le jackpot reste en dernier."""
    def score(c):
        if c["kind"] in ("jackpot", "jackpot_fiable", "mille"):
            return {"jackpot_fiable": -0.5, "jackpot": -1.0}.get(c["kind"], -2.0)
        kf = KIND_FACTOR.get(c["kind"], {}).get("factor", 1.0)
        cf = COMBO_FACTOR.get(signature(c), 1.0) if c["kind"] in SMALL_KINDS else 1.0
        return c["p_not_lose"] * c["reliability"] * kf * cf * (1 + max(min(c["ev"], 0.2), -0.15))
    coupons.sort(key=score, reverse=True)
    n = len(coupons)
    for i, c in enumerate(coupons):
        c["priority"] = i + 1
        c["level"] = "haute" if c["kind"] not in ("jackpot", "jackpot_fiable", "mille") and i < max(1, n // 3) else ("basse" if c["kind"] in ("jackpot", "jackpot_fiable", "audace", "mille") or i >= 2 * n // 3 else "moyenne")
    return coupons


def favorite_leg(pred: dict, home: str, away: str, odds_1x2=None, shift: float = 0.0) -> dict:
    """Sélection « victoire du favori » : l'équipe la plus probable de gagner."""
    res = pred["res"]
    side = "1" if res["1"] >= res["2"] else "2"
    p = float(np.clip(res[side] + shift, 0.02, 0.98))  # correction apprise sur nos résultats
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
        opts = [l for l in m["legs"] if l["market"] in ("o15", "o20") and l["odds"] >= 1.2]
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


RELIABLE: set = set()  # marchés jugés fiables chaque jour (feedback.reliable_markets)
JACKPOT_TARGETS = (10, 20, 50)
JACKPOT_MIN_P = 0.5  # chaque sélection d'un jackpot fiable passe au moins une fois sur deux (testé : 0,6 coûte plus de marge, plus de matchs)


def build_jackpots(matches: list[dict], markets: set | None = None) -> list[dict]:
    """Jackpots cote 10 / 20 / 50 construits uniquement avec les marchés où l'appli est fiable.

    Comme pour la cote 1000 : pour chaque match, la sélection fiable qui apporte le plus de cote
    par unité de risque, puis on empile les meilleures jusqu'à la cote visée.
    """
    markets = RELIABLE if markets is None else markets
    if not markets:
        return []
    cands = []
    for m in matches:
        opts = [l for l in m["legs"] if l["market"] in markets and l["market"] not in COUPON_EXCLUDED and not l.get("p_push")
                and l["odds"] >= 1.15 and l["p_win"] >= JACKPOT_MIN_P]
        if "fav" in markets and m.get("fav") and m["fav"]["odds"] >= 1.15 and m["fav"]["p_win"] >= JACKPOT_MIN_P:
            opts.append(m["fav"])
        if opts:
            best = max(opts, key=lambda l: np.log(l["odds"]) / max(-np.log(max(l["p_win"], 1e-6)), 1e-6))
            cands.append((np.log(best["odds"]) / max(-np.log(max(best["p_win"], 1e-6)), 1e-6), m, best))
    cands.sort(key=lambda x: -x[0])
    out = []
    cfg = COUPONS["jackpot_fiable"]
    for target in JACKPOT_TARGETS:
        picks, odds, p_log = [], 1.0, 0.0
        for _, m, l in cands[:cfg["legs"][1]]:
            picks.append((m, l["market"]))
            odds *= l["odds"]
            p_log += np.log(l["p_win"])
            if odds >= target:
                break
        if odds >= target and len(picks) >= cfg["legs"][0]:
            out.append(_pack("jackpot_fiable", p_log, np.log(odds), picks, scope=f"Cote {target}"))
    return out


def build_long(matches: list[dict], target: float, scope: str, min_p: float = 0.72) -> dict | None:
    """Combiné longue durée : uniquement +1,5, +2 et victoires de gros favoris (probabilité ≥ min_p),
    empilés par ordre d'efficacité (cote gagnée par unité de risque) jusqu'à la cote visée."""
    cands = []
    for m in matches:
        opts = [l for l in m["legs"] if l["market"] in ("o15", "o20") and l["odds"] >= MIN_LEG_ODDS]
        if m.get("fav") and m["fav"]["odds"] >= MIN_LEG_ODDS:
            opts.append(m["fav"])
        for l in opts:
            p_ok = l["p_win"] + l["p_push"]
            if p_ok < min_p:
                continue
            # pour +2, la cote « effective » tient compte du remboursement
            eff_odds = (l["p_win"] * l["odds"] + l["p_push"]) / p_ok
            cands.append((np.log(eff_odds) / max(-np.log(p_ok), 1e-6), m, l))
    cands.sort(key=lambda x: -x[0])
    # on commence par les 2 plus gros favoris (victoire), puis on complète par efficacité
    favs = sorted([c for c in cands if c[2]["market"] in ("1", "2") and c[2]["p_win"] >= 0.75 and c[2]["odds"] >= 1.15],
                  key=lambda c: -c[2]["p_win"])[:2 if target <= 10 else 4]
    cands = favs + [c for c in cands if c not in favs]
    cfg = COUPONS["periode_long"]
    # mélange voulu : +1,5, +2 et gros favoris (au plus 3 sélections +2 et 4 favoris)
    big = target > 10
    quota = {"o20": 7 if big else 3, "1": 7 if big else 4, "2": 7 if big else 4}
    used_q = {"o20": 0, "fav": 0}
    picks, odds, p_log, o_log, seen = [], 1.0, 0.0, 0.0, set()
    for _, m, l in cands:
        if m["id"] in seen or len(picks) >= cfg["legs"][1]:
            continue
        q = "fav" if l["market"] in ("1", "2") else l["market"]
        if q in used_q and used_q[q] >= (quota["o20"] if q == "o20" else quota["1"]):
            continue
        if q in used_q:
            used_q[q] += 1
        seen.add(m["id"])
        picks.append((m, l["market"]))
        odds *= l["odds"]
        st = _leg_stats(l)
        p_log += st[0]
        o_log += st[1]
        if odds >= target:
            break
    if odds < target or len(picks) < cfg["legs"][0]:
        return None
    c = _pack("periode_long", p_log, o_log, picks, scope=scope)
    c["target"] = target
    return c


def settle_leg(market: str, total: int, hg: int = 0, ag: int = 0, info: dict | None = None) -> str | None:
    """None : résultat pas encore connu (score de mi-temps pas encore publié)."""
    if market in extra.EXTRA:
        return extra.settle(market, hg, ag, info)
    if market == "1":
        return "won" if hg > ag else "lost"
    if market == "2":
        return "won" if ag > hg else "lost"
    if market == "o15":
        return "won" if total >= 2 else "lost"
    if market == "o25":
        return "won" if total >= 3 else "lost"
    return "won" if total >= 3 else ("push" if total == 2 else "lost")


def _split(sc):
    """Score enregistré : (buts dom., buts ext.) puis, si connu, un dict {"ht": (buts dom., buts ext.)}."""
    return int(sc[0]), int(sc[1]), (sc[2] if len(sc) >= 3 else None)


def settle_coupon(coupon: dict, scores: dict) -> dict | None:
    """scores : id du match -> score (voir _split). Renvoie None si un résultat manque encore."""
    payout = 1.0
    status = "won"
    # chaque sélection jouée est notée tout de suite, même si le coupon attend encore un match
    ready = True
    for leg in coupon["legs"]:
        if leg["id"] not in scores:
            ready = False
            continue
        hg, ag, info = _split(scores[leg["id"]])
        r = settle_leg(leg["market"], hg + ag, hg, ag, info)
        leg["goals"] = int(hg + ag)
        leg["score"] = f"{hg}-{ag}"
        if r is None:
            ready = False
            leg.pop("result", None)
            continue
        leg["result"] = r
    if not ready:
        return None
    for leg in coupon["legs"]:
        if leg["result"] == "lost":
            status = "lost"
        elif leg["result"] == "won":
            payout *= leg["odds"]
    coupon["status"] = status
    coupon["return"] = round(payout if status == "won" else 0.0, 3)
    return coupon


# Relais : quand un ticket sur plusieurs jours démarre bien (sélections déjà gagnées, aucune perdue),
# un second ticket reprend ses matchs restants avec un pari plus prudent qui va dans le même sens
# (favori remboursé si nul, +2 au lieu de +2,5…). Si le favori gagne, les deux tickets passent ;
# s'il fait nul, le relais est remboursé sur ce match. Il protège sans jamais contredire.
PROTECT = {"1": ("dnb1", "1X"), "2": ("dnb2", "X2"), "dnb1": ("1X",), "dnb2": ("X2",),
           "o25": ("o20", "o15"), "o20": ("o15",), "h15": ("h05",), "a15": ("a05",)}


def build_relay(parent: dict, by_id: dict) -> dict | None:
    """parent : ticket en cours ; by_id : matchs à venir (id -> {"legs": [...], ...})."""
    if parent.get("status") or any(l.get("result") == "lost" for l in parent["legs"]):
        return None
    if not any(l.get("result") == "won" for l in parent["legs"]):
        return None
    picks = []
    for l in parent["legs"]:
        if l.get("result") or l["id"] not in by_id:
            continue
        m = by_id[l["id"]]
        opts = [x for x in m["legs"] if x["market"] in PROTECT.get(l["market"], ())]
        if not opts:
            continue
        best = max(opts, key=lambda x: (x["p_win"] + x["p_push"]) * x["odds"])
        picks.append((m, best))
    if len(picks) < 2:
        return None
    o = float(np.prod([b["odds"] for _, b in picks]))
    if o < COUPONS["relais"]["min_odds"]:
        return None
    p_ok = float(np.prod([b["p_win"] + b["p_push"] for _, b in picks]))
    c = _pack("relais", np.log(p_ok), np.log(o), [(m, b["market"]) for m, b in picks],
              scope=f"protège : {parent['label']}" + (f" · {parent['scope']}" if parent.get("scope") else ""))
    return c
