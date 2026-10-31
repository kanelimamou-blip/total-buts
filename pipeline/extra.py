"""Autres paris choisis par Est : double chance, remboursé si nul, moins de 3,5 / 4,5 buts,
le favori marque +0,5 / +1,5, but en 1re / 2e mi-temps.

Les probabilités viennent de la même grille de scores que les totaux (déjà alignée sur le marché)
et des probabilités 1X2. Un recalibrage appris sur le passé corrige chaque marché,
seulement s'il améliore la précision sur une année jamais vue.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from config import BOOK_MARGIN, VALUE_EDGE
from model import score_matrix, total_dist

# code -> (libellé appli, libellé 1xBet)
LABELS = {
    "1X": ("Double chance 1X", "Double chance 1X"),
    "X2": ("Double chance X2", "Double chance X2"),
    "dnb1": ("Remboursé si nul : domicile", "Victoire 1 remboursé si nul (Handicap 0)"),
    "dnb2": ("Remboursé si nul : extérieur", "Victoire 2 remboursé si nul (Handicap 0)"),
    "u35": ("Moins de 3,5 buts", "Total Moins de 3.5"),
    "u45": ("Moins de 4,5 buts", "Total Moins de 4.5"),
    "h05": ("Domicile marque +0,5", "Total individuel 1 Plus de 0.5"),
    "a05": ("Extérieur marque +0,5", "Total individuel 2 Plus de 0.5"),
    "h15": ("Domicile marque +1,5", "Total individuel 1 Plus de 1.5"),
    "a15": ("Extérieur marque +1,5", "Total individuel 2 Plus de 1.5"),
    "ht05": ("1re mi-temps +0,5 but", "1re mi-temps Total Plus de 0.5"),
    "sh05": ("2e mi-temps +0,5 but", "2e mi-temps Total Plus de 0.5"),
}
EXTRA = set(LABELS)
HALF = {"ht05", "sh05"}

HT_SHARE = 0.44   # part des buts marqués en 1re mi-temps (recalculée sur l'historique dans le backtest)
TEST_DAYS = 365
MIN_GAIN = 0.0005


def raw_probs(xg_h: float, xg_a: float, rho: float, res: dict, ht_share: float = HT_SHARE) -> dict:
    """Probabilités brutes (gagné, remboursé) de chaque marché, côté favori pour les marchés d'équipe."""
    mat = score_matrix(xg_h, xg_a, rho)
    tot = total_dist(mat)
    ph, pa = mat.sum(1), mat.sum(0)   # buts domicile / extérieur
    fav = "1" if res["1"] >= res["2"] else "2"
    lam = xg_h + xg_a
    out = {
        ("1X" if fav == "1" else "X2"): (res[fav] + res["X"], 0.0),
        ("dnb1" if fav == "1" else "dnb2"): (res[fav], res["X"]),
        "u35": (float(tot[:4].sum()), 0.0),
        "u45": (float(tot[:5].sum()), 0.0),
    }
    if fav == "1":
        out["h05"], out["h15"] = (float(1 - ph[0]), 0.0), (float(1 - ph[:2].sum()), 0.0)
    else:
        out["a05"], out["a15"] = (float(1 - pa[0]), 0.0), (float(1 - pa[:2].sum()), 0.0)
    out["ht05"] = (float(1 - np.exp(-lam * ht_share)), 0.0)
    out["sh05"] = (float(1 - np.exp(-lam * (1 - ht_share))), 0.0)
    return out


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def calibrate(cfg: dict | None, market: str, p: float) -> float:
    c = (cfg or {}).get(market)
    if not c or not c.get("use"):
        return p
    a, b = c["coef"]
    return float(1 / (1 + np.exp(-(a + b * _logit(p)))))


def settle(market: str, hg: int, ag: int, info: dict | None = None) -> str | None:
    """Résultat d'une sélection ; None si l'information manque (score de mi-temps pas encore publié).

    info : {"ht": (buts dom., buts ext.)}, la clé pouvant manquer.
    """
    info = info or {}
    t = hg + ag
    if market == "1X":
        return "won" if hg >= ag else "lost"
    if market == "X2":
        return "won" if ag >= hg else "lost"
    if market in ("dnb1", "dnb2"):
        if hg == ag:
            return "push"
        return "won" if (hg > ag) == (market == "dnb1") else "lost"
    if market == "u35":
        return "won" if t <= 3 else "lost"
    if market == "u45":
        return "won" if t <= 4 else "lost"
    if market in ("h05", "h15", "a05", "a15"):
        g = hg if market[0] == "h" else ag
        return "won" if g >= (1 if market.endswith("05") else 2) else "lost"
    if market in HALF:
        ht = info.get("ht")
        if ht is None:
            return None
        h1 = ht[0] + ht[1]
        return "won" if (h1 if market == "ht05" else t - h1) >= 1 else "lost"
    raise ValueError(market)


def legs(xg_h, xg_a, rho, res, cfg=None, ht_share=HT_SHARE) -> list[dict]:
    """Sélections des autres paris pour un match, au format des sélections de buts."""
    out = []
    for mk, (pw, pp) in raw_probs(xg_h, xg_a, rho, res, ht_share).items():
        # le recalibrage porte sur la chance de gagner hors remboursement (voir study)
        pw = calibrate(cfg, mk, pw / max(1 - pp, 1e-9)) * (1 - pp)
        pw = float(np.clip(pw, 0.01, 0.995 - pp))
        fair = (1 - pp) / max(pw, 1e-9)              # cote juste en tenant compte du remboursement
        odds = max(fair / (1 + BOOK_MARGIN), 1.05)
        out.append({"market": mk, "p_win": pw, "p_push": pp, "p_lose": 1 - pw - pp,
                    "odds": round(odds, 2), "odds_source": "estimée", "fair": round(fair, 2),
                    "min_odds": round(fair * (1 + VALUE_EDGE), 2), "ev": pw * odds + pp - 1})
    return out


def study(rows: pd.DataFrame, today: pd.Timestamp) -> dict:
    """rows : une ligne par (match, marché) avec date, market, p (brut, hors remboursement), y (1 gagné, 0 sinon), push (0/1).

    Pour chaque marché : annoncé / réel sur tout l'historique, et recalibrage logistique retenu
    seulement s'il réduit l'erreur sur la dernière année.
    """
    out = {}
    cut = today - pd.Timedelta(days=TEST_DAYS)
    for mk, g in rows.groupby("market"):
        g = g[g["push"] == 0]  # les remboursements ne comptent ni pour ni contre
        tr, te = g[g["date"] < cut], g[g["date"] >= cut]
        entry = {"label": LABELS[mk][0], "n": int(len(g)), "pred": round(float(g["p"].mean()), 3),
                 "obs": round(float(g["y"].mean()), 3), "use": False, "coef": None}
        if len(tr) >= 1000 and len(te) >= 300:
            Xtr, ytr = _logit(tr["p"]), tr["y"].to_numpy(float)

            def obj(b):
                z = b[0] + b[1] * Xtr
                q = 1 / (1 + np.exp(-z))
                return -np.sum(ytr * z - np.logaddexp(0, z)), np.array([np.sum(q - ytr), np.sum((q - ytr) * Xtr)])
            a, b = minimize(obj, np.array([0.0, 1.0]), jac=True, method="L-BFGS-B").x
            p_te = te["p"].to_numpy(float)
            q_te = 1 / (1 + np.exp(-(a + b * _logit(p_te))))
            y = te["y"].to_numpy(float)
            ll = lambda p: float(-np.mean(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1))))
            gain = ll(p_te) - ll(q_te)
            entry.update({"logloss_raw": round(ll(p_te), 5), "logloss_cal": round(ll(q_te), 5),
                          "use": bool(gain >= MIN_GAIN), "coef": [round(float(a), 4), round(float(b), 4)]})
            if entry["use"]:
                q_all = 1 / (1 + np.exp(-(a + b * _logit(g["p"]))))
                entry["pred_cal"] = round(float(q_all.mean()), 3)
        out[mk] = entry
    return out
