"""Modèle Dixon-Coles pondéré dans le temps, avec rappel vers la moyenne."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

from config import MAX_GOALS, RIDGE, TRAIN_DAYS, XI

NEWCOMER_PRIOR = (-0.15, 0.12)  # (attaque, défense) d'une équipe promue, en log


@dataclass
class Ratings:
    teams: dict[str, int]
    att: np.ndarray
    dfn: np.ndarray
    mu: float
    home: float
    rho: float
    n_matches: int

    def rates(self, home: str, away: str) -> tuple[float, float]:
        def get(team):
            i = self.teams.get(team)
            if i is None:
                return NEWCOMER_PRIOR
            return self.att[i], self.dfn[i]
        ah, dh = get(home)
        aa, da = get(away)
        lh = np.exp(self.mu + self.home + ah + da)
        la = np.exp(self.mu + aa + dh)
        return float(lh), float(la)

    def table(self) -> list[dict]:
        rows = []
        for t, i in self.teams.items():
            rows.append({"team": t, "att": round(float(np.exp(self.att[i])), 3),
                         "def": round(float(np.exp(self.dfn[i])), 3)})
        return sorted(rows, key=lambda r: -(r["att"] * r["def"]))


def fit(matches: pd.DataFrame, as_of: pd.Timestamp) -> Ratings | None:
    """Ajuste le modèle sur les matchs joués avant `as_of`."""
    m = matches[(matches["date"] < as_of) & (matches["date"] >= as_of - pd.Timedelta(days=TRAIN_DAYS))]
    if len(m) < 150:
        return None
    teams = sorted(set(m["home"]) | set(m["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    h = m["home"].map(idx).to_numpy()
    a = m["away"].map(idx).to_numpy()
    yh = m["hg"].to_numpy(float)
    ya = m["ag"].to_numpy(float)
    age = (as_of - m["date"]).dt.days.to_numpy(float)
    w = np.exp(-XI * age)

    # Prior : une équipe arrivée en cours de fenêtre est traitée comme promue
    first = pd.concat([m[["date", "home"]].rename(columns={"home": "t"}),
                       m[["date", "away"]].rename(columns={"away": "t"})]).groupby("t")["date"].min()
    start = m["date"].min()
    prior_att = np.zeros(n)
    prior_def = np.zeros(n)
    for t, d in first.items():
        if d > start + pd.Timedelta(days=60):
            prior_att[idx[t]], prior_def[idx[t]] = NEWCOMER_PRIOR

    lam = RIDGE

    def objective(x):
        mu, hm = x[0], x[1]
        att, dfn = x[2:2 + n], x[2 + n:]
        eh = mu + hm + att[h] + dfn[a]
        ea = mu + att[a] + dfn[h]
        lh, la = np.exp(eh), np.exp(ea)
        nll = np.sum(w * (lh - yh * eh)) + np.sum(w * (la - ya * ea))
        nll += lam * (np.sum((att - prior_att) ** 2) + np.sum((dfn - prior_def) ** 2))
        rh, ra = w * (lh - yh), w * (la - ya)
        g = np.zeros_like(x)
        g[0] = rh.sum() + ra.sum()
        g[1] = rh.sum()
        g_att = np.bincount(h, rh, n) + np.bincount(a, ra, n) + 2 * lam * (att - prior_att)
        g_def = np.bincount(a, rh, n) + np.bincount(h, ra, n) + 2 * lam * (dfn - prior_def)
        g[2:2 + n] = g_att
        g[2 + n:] = g_def
        return nll, g

    x0 = np.zeros(2 + 2 * n)
    x0[0] = np.log(max(yh.mean(), 0.5) * 0.9 + max(ya.mean(), 0.5) * 0.1)
    x0[1] = 0.25
    res = minimize(objective, x0, jac=True, method="L-BFGS-B")
    x = res.x
    mu, hm, att, dfn = x[0], x[1], x[2:2 + n], x[2 + n:]

    # rho : recherche sur grille de la correction des petits scores
    lh = np.exp(mu + hm + att[h] + dfn[a])
    la = np.exp(mu + att[a] + dfn[h])
    best_rho, best_ll = 0.0, -np.inf
    for rho in np.linspace(-0.25, 0.15, 41):
        t = np.ones_like(lh)
        t = np.where((yh == 0) & (ya == 0), 1 - lh * la * rho, t)
        t = np.where((yh == 0) & (ya == 1), 1 + lh * rho, t)
        t = np.where((yh == 1) & (ya == 0), 1 + la * rho, t)
        t = np.where((yh == 1) & (ya == 1), 1 - rho, t)
        if np.any(t <= 0):
            continue
        ll = np.sum(w * np.log(t))
        if ll > best_ll:
            best_rho, best_ll = rho, ll
    return Ratings(idx, att, dfn, float(mu), float(hm), float(best_rho), len(m))


_G = np.arange(MAX_GOALS + 1)
_LF = gammaln(_G + 1)


def _pmf(l: float) -> np.ndarray:
    return np.exp(_G * np.log(l) - l - _LF)


def score_matrix(lh: float, la: float, rho: float) -> np.ndarray:
    mat = np.outer(_pmf(lh), _pmf(la))
    mat[0, 0] *= max(1 - lh * la * rho, 1e-6)
    mat[0, 1] *= max(1 + lh * rho, 1e-6)
    mat[1, 0] *= max(1 + la * rho, 1e-6)
    mat[1, 1] *= max(1 - rho, 1e-6)
    return mat / mat.sum()


def total_dist(mat: np.ndarray) -> np.ndarray:
    n = mat.shape[0]
    tot = np.zeros(2 * n - 1)
    for i in range(n):
        tot[i:i + n] += mat[i]
    return tot


def markets_from_total(tot: np.ndarray) -> dict:
    p01 = tot[0] + tot[1]
    p2 = tot[2]
    p3 = 1 - p01 - p2
    return {
        "o15": float(1 - p01),
        "o25": float(p3),
        "o20_win": float(p3),
        "o20_push": float(p2),
        # Plus de 2 (asiatique) : on assimile la probabilité « effective » à p3 / (1 - p2)
        "o20": float(p3 / max(1 - p2, 1e-9)),
    }


def fair_odds(market: str, probs: dict) -> float:
    if market == "o20":
        p3, p01 = probs["o20_win"], 1 - probs["o15"]
        return 1 + p01 / max(p3, 1e-9)
    return 1 / max(probs[market], 1e-9)


def scale_to_target(lh: float, la: float, rho: float, target_o25: float) -> float:
    """Facteur s tel que P(+2,5) du modèle (s·λ) égale la cible du marché."""
    lo, hi = 0.3, 3.0
    for _ in range(40):
        s = (lo + hi) / 2
        p = markets_from_total(total_dist(score_matrix(lh * s, la * s, rho)))["o25"]
        if p < target_o25:
            lo = s
        else:
            hi = s
    return (lo + hi) / 2


def devig(over: float, under: float) -> float | None:
    if not (over and under) or np.isnan(over) or np.isnan(under) or over <= 1 or under <= 1:
        return None
    po, pu = 1 / over, 1 / under
    return po / (po + pu)


def predict(r: Ratings, home: str, away: str, o25=None, u25=None, blend: float = 0.6) -> dict:
    """Probabilités du modèle, puis version ajustée au marché si des cotes existent.

    blend = poids du modèle dans le mélange avec la probabilité implicite du marché (choisi par le backtest).
    """
    lh, la = r.rates(home, away)
    mat = score_matrix(lh, la, r.rho)
    model = markets_from_total(total_dist(mat))
    mkt = devig(o25, u25)
    final_lh, final_la = lh, la
    if mkt is not None:
        target = blend * model["o25"] + (1 - blend) * mkt
        s = scale_to_target(lh, la, r.rho, target)
        final_lh, final_la = lh * s, la * s
        mat = score_matrix(final_lh, final_la, r.rho)
    final = markets_from_total(total_dist(mat))
    flat = [(mat[i, j], i, j) for i in range(6) for j in range(6)]
    top = sorted(flat, reverse=True)[:6]
    return {
        "xg_home": round(final_lh, 2), "xg_away": round(final_la, 2),
        "model": model, "final": final, "market_o25": mkt,
        "top_scores": [{"s": f"{i}-{j}", "p": round(float(p), 3)} for p, i, j in top],
        "total_dist": [round(float(x), 4) for x in total_dist(mat)[:7]],
    }
