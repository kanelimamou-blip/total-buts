"""Méta-modèle : combine le marché, le modèle de buts, les tirs et la ligue.

Les tirs cadrés mesurent la qualité des occasions mieux que les buts seuls (proxy des xG,
gratuit dans les fichiers football-data). Une régression logistique apprend, sur le passé,
comment pondérer chaque signal. Elle n'est utilisée que si elle bat la référence sur
une année de matchs qu'elle n'a jamais vus.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from config import LEAGUES
from model import devig, devig3

ALPHA = 0.12          # poids du dernier match dans la moyenne glissante (≈ 15 derniers matchs)
MIN_GAMES = 5         # en dessous, les tirs d'une équipe ne sont pas pris en compte
TEST_DAYS = 365
MIN_GAIN = 0.0005     # gain minimal de log-loss pour adopter le méta-modèle
L2 = 2.0
DIVS = sorted(LEAGUES)


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def shot_table(results: pd.DataFrame):
    """Moyennes glissantes des tirs par équipe, avant chaque match, et état actuel.

    Renvoie (pre, now) : pre[(div, date, home, away)] -> features du match, now(div, home, away) -> idem.
    """
    cols = ("hst", "ast", "hs", "as_")
    r = results.dropna(subset=list(cols)).sort_values("date")
    teams: dict[str, dict] = {}
    league: dict[str, dict] = {}
    pre = {}

    def team_vals(t):
        s = teams.get(t)
        return s if s and s["n"] >= MIN_GAMES else None

    def feats(div, h, a):
        lg = league.get(div)
        sh, sa = team_vals(h), team_vals(a)
        if lg is None or sh is None or sa is None:
            return {"sot": 0.0, "shots": 0.0, "has_shots": 0.0}
        exp_sot = sh["sotf"] * sa["sota"] / lg["sot"] + sa["sotf"] * sh["sota"] / lg["sot"]
        exp_sh = sh["shf"] * sa["sha"] / lg["sh"] + sa["shf"] * sh["sha"] / lg["sh"]
        return {"sot": float(np.log(exp_sot / (2 * lg["sot"]))), "shots": float(np.log(exp_sh / (2 * lg["sh"]))),
                "has_shots": 1.0}

    for row in r.itertuples():
        pre[(row.div, row.date, row.home, row.away)] = feats(row.div, row.home, row.away)
        for t, f_sot, a_sot, f_sh, a_sh in ((row.home, row.hst, row.ast, row.hs, row.as_),
                                            (row.away, row.ast, row.hst, row.as_, row.hs)):
            s = teams.setdefault(t, {"n": 0, "sotf": f_sot, "sota": a_sot, "shf": f_sh, "sha": a_sh})
            for k, v in (("sotf", f_sot), ("sota", a_sot), ("shf", f_sh), ("sha", a_sh)):
                s[k] = (1 - ALPHA) * s[k] + ALPHA * v
            s["n"] += 1
        lg = league.setdefault(row.div, {"sot": (row.hst + row.ast) / 2, "sh": (row.hs + row.as_) / 2})
        lg["sot"] = 0.99 * lg["sot"] + 0.01 * (row.hst + row.ast) / 2
        lg["sh"] = 0.99 * lg["sh"] + 0.01 * (row.hs + row.as_) / 2
    return pre, feats


def _fav(oh, od, oa):
    if any(x is None or pd.isna(x) for x in (oh, od, oa)):
        return 0.0
    p = devig3(oh, od, oa)
    return abs(p["1"] - p["2"]) if p else 0.0


def design(rows: pd.DataFrame, with_market: bool, target: str) -> np.ndarray:
    """Colonnes : base, écart modèle/base, tirs cadrés, tirs, écart de niveau (cotes 1X2, sinon modèle), ligues."""
    if with_market:
        base = _logit(rows[f"b_{target}"])
        dev = _logit(rows[f"m_{target}"]) - base
    else:
        base = _logit(rows[f"m_{target}"])
        dev = np.zeros(len(rows))
    cols = [base, dev, rows["sot"].to_numpy(float), rows["shots"].to_numpy(float), rows["fav" if with_market else "fav_m"].to_numpy(float),
            np.ones(len(rows))]
    cols += [(rows["div"] == d).to_numpy(float) for d in DIVS]
    return np.column_stack(cols)


def _fit(X, y):
    pen = np.full(X.shape[1], L2)
    pen[0] = 0.0  # la base n'est pas pénalisée : son coefficient recalibre librement

    def obj(b):
        z = X @ b
        p = 1 / (1 + np.exp(-z))
        ll = -np.sum(y * z - np.logaddexp(0, z)) + 0.5 * np.sum(pen * b * b)
        g = X.T @ (p - y) + pen * b
        return ll, g
    b0 = np.zeros(X.shape[1])
    b0[0] = 1.0
    return minimize(obj, b0, jac=True, method="L-BFGS-B").x


def _ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def predict_p(coef, x) -> float:
    return float(1 / (1 + np.exp(-(np.asarray(x) @ np.asarray(coef)))))


def study(bt: pd.DataFrame, today: pd.Timestamp) -> dict:
    """bt : lignes du backtest avec m_o15, m_o25, b_o15, b_o25 (marché), sot, shots, fav, y15, y25."""
    out = {}
    cut = today - pd.Timedelta(days=TEST_DAYS)
    for with_market in (True, False):
        sub = bt[bt["b_o25"].notna()] if with_market else bt
        tr, te = sub[sub["date"] < cut], sub[sub["date"] >= cut]
        key = "market" if with_market else "no_market"
        out[key] = {}
        for target, y in (("o15", "y15"), ("o25", "y25")):
            if len(tr) < 2000 or len(te) < 500:
                continue
            ref_col = f"b_{target}" if with_market else f"m_{target}"
            coef = _fit(design(tr, with_market, target), tr[y].to_numpy(float))
            p = 1 / (1 + np.exp(-(design(te, with_market, target) @ coef)))
            ll_ref, ll_new = _ll(te[ref_col].to_numpy(float), te[y].to_numpy()), _ll(p, te[y].to_numpy())
            # même test sans les tirs : mesure ce que les tirs apportent à eux seuls
            Xs = design(tr, with_market, target); Xs[:, 2:4] = 0
            Xt = design(te, with_market, target); Xt[:, 2:4] = 0
            p_ns = 1 / (1 + np.exp(-(Xt @ _fit(Xs, tr[y].to_numpy(float)))))
            use = ll_ref - ll_new >= MIN_GAIN
            full = _fit(design(sub, with_market, target), sub[y].to_numpy(float)) if use else None
            out[key][target] = {
                "n_train": int(len(tr)), "n_test": int(len(te)),
                "logloss_ref": round(ll_ref, 5), "logloss_meta": round(ll_new, 5),
                "logloss_no_shots": round(_ll(p_ns, te[y].to_numpy()), 5),
                "gain_pct": round(100 * (ll_ref - ll_new) / ll_ref, 2),
                "use": bool(use), "coef": None if full is None else [round(float(c), 5) for c in full],
                "weights": {"base": round(float(coef[0]), 3), "modele": round(float(coef[1]), 3),
                            "tirs_cadres": round(float(coef[2]), 3), "tirs": round(float(coef[3]), 3),
                            "ecart_niveau": round(float(coef[4]), 3)},
            }
    return out


def row_features(shots: dict, res_model: dict, oh=None, od=None, oa=None) -> dict:
    """res_model : probabilités 1X2 du modèle seul (sert d'écart de niveau quand il n'y a pas de cotes)."""
    return {"sot": shots["sot"], "shots": shots["shots"], "fav": _fav(oh, od, oa),
            "fav_m": abs(res_model["1"] - res_model["2"])}


def apply(cfg: dict | None, div: str, feats: dict, m15: float, m25: float, b15=None, b25=None):
    """Probabilités +1,5 et +2,5 du méta-modèle (None si non retenu pour ce cas)."""
    if not cfg:
        return None, None
    key = "market" if b25 is not None else "no_market"
    row = pd.DataFrame([{"div": div, "m_o15": m15, "m_o25": m25, "b_o15": b15, "b_o25": b25, **feats}])
    res = []
    for target in ("o15", "o25"):
        c = cfg.get(key, {}).get(target)
        res.append(predict_p(c["coef"], design(row, b25 is not None, target)[0]) if c and c.get("use") else None)
    return tuple(res)
