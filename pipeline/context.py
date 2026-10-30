"""Facteurs de contexte : ce que la force des équipes ne dit pas.

On mesure, sur l'historique, si les buts s'écartent des probabilités du modèle selon :
- le type d'affiche (haut / milieu / bas de tableau au moment du match),
- la période de la saison,
- le retour de trêve internationale,
- un match européen dans les 4 jours précédents (fatigue),
- un repos court ou un calendrier chargé.
Chaque facteur devient un petit ajustement des probabilités (en logit). L'ajustement n'est
appliqué que s'il améliore les prédictions sur une période de test jamais vue pendant l'apprentissage.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.optimize import minimize

FEATURES = {
    "top_top": "Choc entre deux équipes du haut de tableau",
    "top_bottom": "Haut de tableau contre bas de tableau",
    "top_mid": "Haut de tableau contre milieu",
    "mid_bottom": "Milieu contre bas de tableau",
    "bottom_bottom": "Deux équipes du bas de tableau",
    "aug": "Début de saison (août)",
    "nov_dec": "Novembre-décembre",
    "jan_feb": "Janvier-février",
    "mar_apr": "Mars-avril",
    "may_jun": "Fin de saison (mai-juin)",
    "post_break": "Retour de trêve internationale",
    "euro_recent": "Match européen dans les 4 jours avant",
    "short_rest": "Repos de 3 jours ou moins",
    "congested": "4 matchs ou plus en 14 jours",
}
L2 = 4.0


def _season(d: pd.Timestamp) -> int:
    return d.year if d.month >= 7 else d.year - 1


def team_states(results: pd.DataFrame, cup_games: pd.DataFrame | None = None):
    """Pour chaque match (passé ou à venir), l'état des équipes juste avant : rang, repos, fatigue.

    Renvoie une fonction state(div, date, team) calculée sur les matchs strictement antérieurs.
    """
    games = defaultdict(list)  # équipe -> dates de matchs (championnat + Europe)
    euro = defaultdict(list)
    for r in results.itertuples():
        games[r.home].append(r.date)
        games[r.away].append(r.date)
    if cup_games is not None and len(cup_games):
        for r in cup_games.itertuples():
            for t in (r.home, r.away):
                games[t].append(r.date)
                euro[t].append(r.date)
    games = {t: np.array(sorted(v), dtype="datetime64[ns]") for t, v in games.items()}
    euro = {t: np.array(sorted(v), dtype="datetime64[ns]") for t, v in euro.items()}

    # classement (points par match) avant chaque journée, par ligue et saison
    table = {}
    for (div, season), g in results.assign(season=results["date"].map(_season)).groupby(["div", "season"]):
        pts, n = defaultdict(float), defaultdict(int)
        snapshots = []
        for d, day in g.groupby("date"):
            snapshots.append((d, {t: pts[t] / n[t] for t in n if n[t] >= 3}))
            for r in day.itertuples():
                n[r.home] += 1
                n[r.away] += 1
                pts[r.home] += 3 if r.hg > r.ag else (1 if r.hg == r.ag else 0)
                pts[r.away] += 3 if r.ag > r.hg else (1 if r.hg == r.ag else 0)
        snapshots.append((pd.Timestamp.max, {t: pts[t] / n[t] for t in n if n[t] >= 3}))
        table[(div, season)] = snapshots

    def rank_pct(div, date, team):
        snaps = table.get((div, _season(date)))
        if not snaps:
            return None
        ppg = None
        for d, s in snaps:
            if d >= date:
                ppg = s
                break
        if not ppg or team not in ppg or len(ppg) < 8:
            return None
        vals = sorted(ppg.values(), reverse=True)
        return vals.index(ppg[team]) / (len(vals) - 1)

    def state(div, date, team):
        d64 = np.datetime64(date)
        g = games.get(team)
        prev = g[g < d64] if g is not None else np.array([], dtype="datetime64[ns]")
        rest = (d64 - prev[-1]).astype("timedelta64[D]").astype(int) if len(prev) else None
        recent = int(((d64 - prev) <= np.timedelta64(14, "D")).sum()) if len(prev) else 0
        e = euro.get(team)
        eu = bool(e is not None and len(e) and ((d64 - e[e < d64]) <= np.timedelta64(4, "D")).any())
        return {"rank": rank_pct(div, date, team), "rest": rest, "recent14": recent, "euro": eu}

    return state


def cup_games_fd(results: pd.DataFrame) -> pd.DataFrame:
    """Matchs européens des clubs des 10 championnats, avec les noms football-data."""
    import ahead
    import europe
    e = europe.load()
    a = ahead._load()
    if e.empty:
        return pd.DataFrame(columns=["date", "home", "away"])
    espn = pd.concat([e, a], ignore_index=True) if len(a) else e
    names = ahead.name_map(espn, results)
    flat = {}
    for m in names.values():
        flat.update(m)
    cups = e[e["completed"] & e["slug"].isin(europe.CUPS)]
    rows = [{"date": pd.Timestamp(r.dt.date()), "home": flat.get(r.home, r.home), "away": flat.get(r.away, r.away)}
            for r in cups.itertuples()]
    return pd.DataFrame(rows)


def tier(p):
    if p is None:
        return "mid"
    return "top" if p <= 0.25 else ("bottom" if p >= 0.75 else "mid")


def features(div, date, sh: dict, sa: dict) -> dict:
    t = sorted([tier(sh["rank"]), tier(sa["rank"])], key=["top", "mid", "bottom"].index)
    pair = f"{t[0]}_{t[1]}"
    f = {k: 0.0 for k in FEATURES}
    if pair in f:
        f[pair] = 1.0
    m = date.month
    phase = {8: "aug", 11: "nov_dec", 12: "nov_dec", 1: "jan_feb", 2: "jan_feb", 3: "mar_apr", 4: "mar_apr",
             5: "may_jun", 6: "may_jun"}.get(m)
    if phase:
        f[phase] = 1.0
    rests = [x for x in (sh["rest"], sa["rest"]) if x is not None]
    if len(rests) == 2 and min(rests) >= 11 and m in (9, 10, 11, 3, 6) and sh["rank"] is not None:
        f["post_break"] = 1.0
    if sh["euro"] or sa["euro"]:
        f["euro_recent"] = 1.0
    if rests and min(rests) <= 3:
        f["short_rest"] = 1.0
    if max(sh["recent14"], sa["recent14"]) >= 4:
        f["congested"] = 1.0
    return f


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _fit(X, base, y):
    def obj(b):
        z = base + X @ b
        p = 1 / (1 + np.exp(-z))
        ll = -np.sum(y * np.log(np.clip(p, 1e-9, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-9, 1)))
        return ll + L2 * b @ b, X.T @ (p - y) + 2 * L2 * b
    return minimize(obj, np.zeros(X.shape[1]), jac=True, method="L-BFGS-B").x


def _ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def study(rows: pd.DataFrame) -> dict:
    """rows : div, date, tot, f_o15, f_o25 + colonnes de FEATURES. Apprentissage sur les 2/3 les plus anciens,
    test sur le dernier tiers, puis coefficients finaux sur tout l'historique si le test est concluant."""
    keys = list(FEATURES)
    rows = rows.dropna(subset=["f_o15", "f_o25"]).sort_values("date")
    X = rows[keys].to_numpy(float)
    split = int(len(rows) * 2 / 3)
    out = {"n": int(len(rows)), "markets": {}, "factors": []}
    for mk, thr in (("o15", 2), ("o25", 3)):
        y = (rows["tot"] >= thr).to_numpy(float)
        base = _logit(rows[f"f_{mk}"].to_numpy(float))
        b = _fit(X[:split], base[:split], y[:split])
        p0 = 1 / (1 + np.exp(-base[split:]))
        p1 = 1 / (1 + np.exp(-(base[split:] + X[split:] @ b)))
        gain = _ll(p0, y[split:]) - _ll(p1, y[split:])
        bf = _fit(X, base, y)
        out["markets"][mk] = {"test_logloss_base": round(_ll(p0, y[split:]), 5), "test_logloss_ctx": round(_ll(p1, y[split:]), 5),
                              "gain": round(gain, 5), "use": bool(gain > 0), "coef": dict(zip(keys, np.round(bf, 4).tolist()))}
    p25 = rows["f_o25"].to_numpy(float)
    y25 = (rows["tot"] >= 3).to_numpy(float)
    for i, k in enumerate(keys):
        sel = X[:, i] == 1
        if sel.sum() >= 80:
            out["factors"].append({"key": k, "label": FEATURES[k], "n": int(sel.sum()),
                                   "pred_o25": round(float(p25[sel].mean()), 3), "obs_o25": round(float(y25[sel].mean()), 3),
                                   "goals": round(float(rows["tot"][sel].mean()), 2)})
    out["factors"].sort(key=lambda f: -abs(f["obs_o25"] - f["pred_o25"]))
    return out


def adjust(final: dict, feats: dict, cfg: dict | None) -> dict:
    """Applique les ajustements validés aux probabilités finales d'un match."""
    if not cfg:
        return final
    f = dict(final)
    x = np.array([feats.get(k, 0.0) for k in FEATURES])
    for mk in ("o15", "o25"):
        m = cfg.get("markets", {}).get(mk)
        if m and m.get("use"):
            b = np.array([m["coef"].get(k, 0.0) for k in FEATURES])
            f[mk] = float(1 / (1 + np.exp(-(_logit(f[mk]) + x @ b))))
    f["o25"] = min(f["o25"], f["o15"] - 0.005)
    f["o20_win"] = f["o25"]
    f["o20_push"] = max(f["o15"] - f["o25"], 0.0)
    f["o20"] = f["o25"] / max(1 - f["o20_push"], 1e-9)
    return f
