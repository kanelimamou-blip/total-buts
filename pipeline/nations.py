"""Modèle dédié aux sélections européennes (demande d'Est, 2026-11-07).

Données : résultats de tous les matchs internationaux (jeu public martj42/international_results, mis à jour
régulièrement). Modèle de Poisson : attaque et défense par sélection, avantage du terrain seulement quand le match
n'est pas sur terrain neutre, matchs récents plus lourds (demi-vie 2 ans), amicaux comptés à moitié.
Il n'y a pas de cotes du marché pour ces matchs : les probabilités viennent du seul modèle, puis sont recalibrées sur
le test rejoué. Le modèle reste en observation tant que le test ne montre pas qu'il annonce juste.
"""
from __future__ import annotations

import io
import urllib.request

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
HALF_LIFE_DAYS = 730
TRAIN_YEARS = 8
FRIENDLY_WEIGHT = 0.5
UEFA_COMPS = ("UEFA Nations League", "UEFA Euro qualification", "UEFA Euro")
MAX_GOALS = 10


def load(path=None) -> pd.DataFrame:
    if path:
        raw = open(path, "rb").read()
    else:
        with urllib.request.urlopen(URL, timeout=60) as r:
            raw = r.read()
    d = pd.read_csv(io.BytesIO(raw), parse_dates=["date"])
    d = d.dropna(subset=["home_score", "away_score"])
    d["neutral"] = d["neutral"].astype(str).str.upper() == "TRUE"
    return d.rename(columns={"home_team": "home", "away_team": "away", "home_score": "hg", "away_score": "ag"})


def uefa_teams(d: pd.DataFrame) -> set:
    u = d[d["tournament"].isin(UEFA_COMPS) & (d["date"] >= "2016-01-01")]
    return set(u["home"]) | set(u["away"])


class Ratings:
    def __init__(self, teams, att, dfn, mu, hfa):
        self.idx = {t: i for i, t in enumerate(teams)}
        self.att, self.dfn, self.mu, self.hfa = att, dfn, mu, hfa

    def known(self, t):
        return t in self.idx

    def rates(self, home, away, neutral=True):
        i, j = self.idx[home], self.idx[away]
        lh = np.exp(self.mu + self.att[i] - self.dfn[j] + (0 if neutral else self.hfa))
        la = np.exp(self.mu + self.att[j] - self.dfn[i])
        return float(lh), float(la)


def fit(d: pd.DataFrame, as_of: pd.Timestamp) -> Ratings | None:
    m = d[(d["date"] < as_of) & (d["date"] >= as_of - pd.Timedelta(days=365 * TRAIN_YEARS))]
    if len(m) < 500:
        return None
    teams = sorted(set(m["home"]) | set(m["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = m["home"].map(idx).to_numpy()
    ai = m["away"].map(idx).to_numpy()
    hg = m["hg"].to_numpy(float)
    ag = m["ag"].to_numpy(float)
    home = (~m["neutral"]).to_numpy(float)
    age = (as_of - m["date"]).dt.days.to_numpy(float)
    w = 0.5 ** (age / HALF_LIFE_DAYS) * np.where(m["tournament"].eq("Friendly"), FRIENDLY_WEIGHT, 1.0)

    def nll(x):
        att, dfn, mu, hfa = x[:n], x[n:2 * n], x[-2], x[-1]
        lh = mu + att[hi] - dfn[ai] + hfa * home
        la = mu + att[ai] - dfn[hi]
        el, ea = np.exp(lh), np.exp(la)
        f = np.sum(w * (el - hg * lh + ea - ag * la)) + 2.0 * (np.sum(att ** 2) + np.sum(dfn ** 2))
        g_h = w * (el - hg)
        g_a = w * (ea - ag)
        gatt = np.bincount(hi, g_h, n) + np.bincount(ai, g_a, n) + 4.0 * att
        gdef = -np.bincount(ai, g_h, n) - np.bincount(hi, g_a, n) + 4.0 * dfn
        return f, np.concatenate([gatt, gdef, [g_h.sum() + g_a.sum(), np.sum(g_h * home)]])

    x0 = np.zeros(2 * n + 2)
    x0[-2] = np.log(max((hg.mean() + ag.mean()) / 2, 0.3))
    res = minimize(nll, x0, jac=True, method="L-BFGS-B")
    x = res.x
    return Ratings(teams, x[:n], x[n:2 * n], x[-2], x[-1])


def probs(lh: float, la: float) -> dict:
    g = np.arange(MAX_GOALS + 1)
    M = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    tot = np.zeros(2 * MAX_GOALS + 1)
    for i in g:
        tot[i:i + MAX_GOALS + 1] += M[i]
    return {
        "o15": float(tot[2:].sum()), "o25": float(tot[3:].sum()), "o20_win": float(tot[3:].sum()), "o20_push": float(tot[2]),
        "1": float(np.tril(M, -1).sum()), "X": float(np.trace(M)), "2": float(np.triu(M, 1).sum()),
    }


def walk_forward(d: pd.DataFrame, start="2021-01-01", step_days=30) -> pd.DataFrame:
    """Rejoue les matchs entre sélections européennes : chaque mois, le modèle est réajusté sur le passé seul."""
    teams = uefa_teams(d)
    target = d[(d["date"] >= start) & d["home"].isin(teams) & d["away"].isin(teams)]
    rows = []
    t = pd.Timestamp(start)
    end = d["date"].max() + pd.Timedelta(days=1)
    while t < end:
        nxt = t + pd.Timedelta(days=step_days)
        block = target[(target["date"] >= t) & (target["date"] < nxt)]
        if len(block):
            r = fit(d, t)
            if r:
                for x in block.itertuples():
                    if r.known(x.home) and r.known(x.away):
                        lh, la = r.rates(x.home, x.away, x.neutral)
                        p = probs(lh, la)
                        rows.append({"date": x.date, "home": x.home, "away": x.away, "tournament": x.tournament,
                                     "friendly": x.tournament == "Friendly", "hg": x.hg, "ag": x.ag, **p})
        t = nxt
    return pd.DataFrame(rows)


def report(bt: pd.DataFrame) -> dict:
    """Annoncé / réel par marché et par tranche de probabilité, avec la base « taux moyen » pour comparer."""
    tot = bt["hg"] + bt["ag"]
    fav_home = bt["1"] >= bt["2"]
    out = {"n": int(len(bt)), "markets": {}}
    ys = {"o15": tot >= 2, "o25": tot >= 3,
          "fav": np.where(fav_home, bt["hg"] > bt["ag"], bt["ag"] > bt["hg"])}
    ps = {"o15": bt["o15"], "o25": bt["o25"], "fav": np.where(fav_home, bt["1"], bt["2"])}
    for k in ys:
        y, p = np.asarray(ys[k], float), np.asarray(ps[k], float)
        ll = -np.mean(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1)))
        base = y.mean()
        ll0 = -np.mean(y * np.log(base) + (1 - y) * np.log(1 - base))
        bands = []
        for lo, hi in ((0, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
            s = (p >= lo) & (p < hi)
            if s.sum() >= 20:
                bands.append({"band": f"{int(lo*100)}-{int(min(hi,1)*100)} %", "n": int(s.sum()),
                              "pred": round(float(p[s].mean()), 3), "real": round(float(y[s].mean()), 3)})
        out["markets"][k] = {"pred": round(float(p.mean()), 3), "real": round(float(base), 3),
                             "logloss": round(float(ll), 4), "logloss_base": round(float(ll0), 4), "bands": bands}
    return out


# ---------------------------------------------------------------- calendrier et intégration à l'appli
NAT_SLUGS = ["uefa.nations", "fifa.worldq.uefa", "uefa.euroq", "fifa.friendly"]
CODE, LEAGUE = "NAT", "Sélections européennes"
FAV_CAL = (0.006, 1.116)  # recalibrage du favori appris sur le test (2021-2024), vérifié sur 2024-2026
ALIASES = {"Czech Republic": "Czechia", "Turkey": "Türkiye", "Turkiye": "Türkiye", "Ireland": "Republic of Ireland",
           "Bosnia-Herzegovina": "Bosnia and Herzegovina", "Bosnia & Herzegovina": "Bosnia and Herzegovina",
           "North Macedonia": "North Macedonia", "Macedonia": "North Macedonia", "Kosovo": "Kosovo",
           "Faroe Islands": "Faroe Islands", "Holland": "Netherlands", "USA": "United States"}


def _name(espn_name: str, known: set) -> str | None:
    import difflib
    n = ALIASES.get(espn_name, espn_name)
    if n in known:
        return n
    for k in known:  # « Türkiye » / « Turkey » selon la version du jeu de données
        if ALIASES.get(k) == n:
            return k
    m = difflib.get_close_matches(n, list(known), n=1, cutoff=0.85)
    return m[0] if m else None


def _fav_p(p):
    a, b = FAV_CAL
    x = np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
    return float(1 / (1 + np.exp(-(a + b * x))))


def update(today, cache_dir, offline=False):
    """Matchs à venir entre sélections européennes (format des coupes d'Europe) et scores récents.
    Renvoie (à venir, scores, rapport du test)."""
    import json
    from datetime import timedelta
    import europe
    from model import markets_from_total, result_probs, score_matrix, total_dist
    cache_dir.mkdir(parents=True, exist_ok=True)
    csv = cache_dir / "intl_results.csv"
    if not offline:
        try:
            with urllib.request.urlopen(URL, timeout=60) as r:
                csv.write_bytes(r.read())
        except Exception as exc:  # noqa: BLE001
            print("Résultats internationaux indisponibles, cache utilisé :", exc)
    if not csv.exists():
        return [], {}, None
    d = load(str(csv))
    teams = uefa_teams(d)
    rows = []
    rec = cache_dir / "nations_recent.json"
    if not offline:
        days = europe._chunk_days(today) or 1
        for slug in NAT_SLUGS:
            x = today - timedelta(days=4)
            while x <= today + timedelta(days=10):
                rows += europe._fetch(slug, x, days) or []
                x += timedelta(days=days)
        rec.write_text(json.dumps(rows))
    elif rec.exists():
        rows = json.loads(rec.read_text())
    now = pd.Timestamp.now(tz="UTC")
    r = fit(d, now.tz_localize(None))
    upcoming, scores, seen = [], {}, set()
    for x in rows:
        h, a = _name(x["home"], teams), _name(x["away"], teams)
        if not h or not a:
            continue
        dt = pd.Timestamp(x["dt"])
        mid = f"{dt.strftime('%Y%m%d')}|{CODE}|{h}|{a}"
        if mid in seen:
            continue
        seen.add(mid)
        if x.get("completed") and x.get("hg") is not None:
            scores[mid] = (int(x["hg"]), int(x["ag"]))
            continue
        if x.get("state") in ("in", "post") or dt < now or r is None or not (r.known(h) and r.known(a)):
            continue
        lh, la = r.rates(h, a, neutral=False)  # Ligue des nations, qualifications, amicaux : presque toujours chez l'équipe qui reçoit
        mat = score_matrix(lh, la, 0.0)
        final = markets_from_total(total_dist(mat))
        res = result_probs(mat)
        side = "1" if res["1"] >= res["2"] else "2"
        res[side] = _fav_p(res[side])
        flat = sorted(((mat[i, j], i, j) for i in range(6) for j in range(6)), reverse=True)[:6]
        upcoming.append({
            "id": mid, "div": CODE, "league": LEAGUE, "country": "Europe", "nations": True,
            "date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M"), "home": h, "away": a,
            "lh": lh, "la": la, "final": final, "res": res, "espn": [x["slug"], x.get("espn_id")],
            "top_scores": [{"s": f"{i}-{j}", "p": round(float(p), 3)} for p, i, j in flat],
            "total_dist": [round(float(t), 4) for t in total_dist(mat)[:7]],
            "form_home": None, "form_away": None,
        })
    return upcoming, scores, d
