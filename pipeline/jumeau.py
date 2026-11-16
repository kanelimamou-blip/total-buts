"""Jumeau de l'appli : mêmes matchs, mêmes calculs, mais une seule règle, la moins perdante sur 3 ans.

Étude du 16/11/2026 (17 218 coupons rejoués de sept. 2023 à nov. 2026, coupés avant et après août 2025 pour ne
pas garder un hasard) : après la taxe de 20 %, aucun type de coupon ne gagne. L'appli entière perd environ 23 %
par mise. La règle la plus stable est le coupon « mix » de 2 ou 3 matchs à cote 2 à 2,6, au plus 2 par jour :
environ −11 % par mise, la même chose chaque année (−15 % en 2023, −10 % en 2024, −13 % en 2025, −9 % en 2026).
Chaque match ajouté coûte la marge du bookmaker une fois de plus : c'est la première cause des pertes.

Le jumeau choisit parmi les coupons déjà calculés par l'appli : il ne touche à rien d'autre.
"""
from __future__ import annotations

from config import TAX

RULE = {"kind": "mix", "min_odds": 2.0, "max_odds": 2.6, "max_legs": 3, "per_day": 2}
START = "2026-11-17"  # suivi réel du jumeau à partir de ce jour (règle choisie le 16/11)


def select(day_coupons: list[dict]) -> list[dict]:
    """Les coupons du jour que le jumeau joue : au plus 2, les plus sûrs, sans match en commun."""
    ok = [c for c in day_coupons if c["kind"] == RULE["kind"] and RULE["min_odds"] <= c["odds"] <= RULE["max_odds"]
          and len(c["legs"]) <= RULE["max_legs"]]
    ok.sort(key=lambda c: -c["p_not_lose"])
    out, used = [], set()
    for c in ok:
        ids = {l["id"] for l in c["legs"]}
        if len(out) >= RULE["per_day"] or ids & used:
            continue
        used |= ids
        out.append(c)
    return out


def net(c: dict) -> float:
    """Gain net pour une mise de 1, taxe déduite (remboursé = 0)."""
    if c.get("status") == "won":
        r = c.get("return", c["odds"])
        return (r - 1) * (1 - TAX) if r > 1 else r - 1
    return -1.0 if c.get("status") == "lost" else 0.0


def summary(coupons: list[dict]) -> dict:
    done = [c for c in coupons if c.get("status") in ("won", "lost")]
    n = len(done)
    if not n:
        return {"n": 0}
    return {"n": n, "won": sum(c["status"] == "won" for c in done), "pred": round(sum(c["p_not_lose"] for c in done) / n, 3),
            "net": round(sum(net(c) for c in done), 2), "roi": round(sum(net(c) for c in done) / n, 4)}
