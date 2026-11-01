"""Coupes d'Europe (Ligue des Champions, Ligue Europa, Conference League).

Source gratuite : l'API publique des tableaux de scores d'ESPN (sans clé).
Pour comparer des équipes de pays différents, on ajuste un modèle unique sur les championnats
de toute l'Europe et les matchs européens : chaque championnat reçoit un niveau (attaque/défense)
et chaque équipe un écart à ce niveau. Les matchs européens relient les championnats entre eux.
Il n'y a pas de cotes gratuites pour ces matchs : les probabilités viennent du modèle seul.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
from scipy.optimize import minimize

from config import RAW_DIR, XI

ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
CUPS = {
    "uefa.champions": ("UCL", "Ligue des Champions"),
    "uefa.europa": ("UEL", "Ligue Europa"),
    "uefa.europa.conf": ("UECL", "Conference League"),
}
# Championnats dont les clubs jouent régulièrement les coupes d'Europe
DOMESTIC = ["eng.1", "esp.1", "fra.1", "ita.1", "ger.1", "por.1", "tur.1", "ned.1",
            "bel.1", "sco.1", "aut.1", "sui.1", "gre.1", "den.1", "cze.1", "nor.1", "swe.1",
            "isr.1", "cyp.1", "rou.1"]  # pol.1, cro.1, srb.1, ukr.1, hun.1 : refusés par la source (erreur 400 à chaque appel)
CACHE = RAW_DIR / "espn"
HISTORY_DAYS = 760
MAX_REQUESTS = 3500
MIN_COVERAGE_DAYS = 300  # en dessous, les matchs européens sont affichés mais pas mis en coupon
RIDGE_TEAM = 3.0
RIDGE_LEAGUE = 0.3


STATUS: dict = {}


def _get(url, params):
    key = url.split("/soccer/")[1].split("/")[0]
    st = STATUS.setdefault(key, {"ok": 0, "fail": 0, "last": None})
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "Mozilla/5.0 (total-buts)"})
            st["last"] = r.status_code
            if r.status_code in (400, 404):
                st["fail"] += 1
                return None
            r.raise_for_status()
            st["ok"] += 1
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            st["last"] = str(exc)[:120]
            time.sleep(2 ** attempt)
    st["fail"] += 1
    return None


def _parse(payload, slug):
    rows = []
    for e in (payload or {}).get("events", []):
        try:
            c = e["competitions"][0]
            teams = {t["homeAway"]: t for t in c["competitors"]}
            st = c.get("status", e.get("status", {})).get("type", {})
            dt = pd.Timestamp(e["date"]).tz_convert("UTC")
            row = {"slug": slug, "espn_id": e.get("id"), "dt": dt.isoformat(),
                   "home": teams["home"]["team"]["displayName"], "away": teams["away"]["team"]["displayName"],
                   "completed": bool(st.get("completed")), "state": st.get("state", ""), "hg": None, "ag": None}
            if row["completed"] or row["state"] == "in":
                row["hg"], row["ag"] = int(float(teams["home"]["score"])), int(float(teams["away"]["score"]))
            if row["state"] == "in":  # minute en cours, pour les paris live
                clock = c.get("status", e.get("status", {})).get("displayClock", "") or ""
                digits = "".join(ch for ch in clock.split("'")[0].split(":")[0] if ch.isdigit())
                row["minute"] = int(digits) if digits else 0
            rows.append(row)
        except (KeyError, ValueError, TypeError, IndexError):
            continue
    return rows


def _fetch(slug: str, start: date, days: int):
    """Une requête couvrant `days` jours ; None si la source refuse."""
    end = start + timedelta(days=days - 1)
    dates = f"{start:%Y%m%d}" if days == 1 else f"{start:%Y%m%d}-{end:%Y%m%d}"
    data = _get(ESPN.format(slug=slug), {"dates": dates, "limit": 500})
    return None if data is None else _parse(data, slug)


def _chunk_days(today: date) -> int:
    """La source refuse les longues périodes : on garde la plus longue acceptée (mémorisée)."""
    path = CACHE / "_chunk.json"
    try:
        return json.loads(path.read_text())["days"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    for days in (14, 7, 3, 1):
        if _fetch("uefa.champions", today - timedelta(days=days + 7), days) is not None:
            path.write_text(json.dumps({"days": days}))
            return days
    return 0


def download(today: date) -> None:
    """Téléchargement progressif : à venir et récent à chaque passage, puis l'historique
    manquant du plus récent au plus ancien, dans la limite de MAX_REQUESTS par passage."""
    CACHE.mkdir(parents=True, exist_ok=True)
    days = _chunk_days(today)
    STATUS["_chunk_days"] = days
    budget = MAX_REQUESTS
    if days:
        # 1. matchs européens à venir et des derniers jours (rafraîchis à chaque passage)
        for slug in CUPS:
            rows = []
            d = today - timedelta(days=4)
            while d <= today + timedelta(days=8):
                got = _fetch(slug, d, days)
                budget -= 1
                rows += got or []
                d += timedelta(days=days)
            (CACHE / f"{slug}_recent.json").write_text(json.dumps(rows))
        # 2. historique manquant (les blocs terminés ne sont plus jamais retéléchargés)
        first = today - timedelta(days=HISTORY_DAYS)
        starts = []
        d = date.fromordinal(first.toordinal() - first.toordinal() % days)
        while d + timedelta(days=days) <= today - timedelta(days=4):
            starts.append(d)
            d += timedelta(days=days)
        for start in reversed(starts):
            for slug in list(CUPS) + DOMESTIC:
                path = CACHE / f"{slug}_{start:%Y%m%d}_{days}.json"
                if path.exists():
                    continue
                if budget <= 0:
                    break
                got = _fetch(slug, start, days)
                budget -= 1
                if got is not None:
                    path.write_text(json.dumps(got))
            if budget <= 0:
                break
    STATUS["_budget_left"] = budget
    (RAW_DIR.parent / "state").mkdir(parents=True, exist_ok=True)
    (RAW_DIR.parent / "state" / "europe_status.json").write_text(json.dumps(STATUS, indent=1))


def load() -> pd.DataFrame:
    rows = []
    for p in sorted(CACHE.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            rows += json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["dt"], utc=True)
    df = df.sort_values("completed").drop_duplicates("espn_id", keep="last")
    return df.sort_values("dt").reset_index(drop=True)


class Global:
    def __init__(self, teams, team_league, att, dfn, latt, ldef, mu, home, rho, leagues, cup_mu=None):
        self.cup_mu = cup_mu or {}
        self.teams, self.team_league = teams, team_league
        self.att, self.dfn, self.latt, self.ldef = att, dfn, latt, ldef
        self.mu, self.home, self.rho, self.leagues = mu, home, rho, leagues

    def known(self, t):
        return t in self.teams

    def _ad(self, t):
        i = self.teams[t]
        l = self.team_league[i]
        return self.latt[l] + self.att[i], self.ldef[l] + self.dfn[i]

    def rates(self, home, away, neutral=False, slug=None):
        ah, dh = self._ad(home)
        aa, da = self._ad(away)
        hm = 0.0 if neutral else self.home
        c = self.cup_mu.get(slug, 0.0)  # niveau de buts propre à chaque coupe d'Europe
        return float(np.exp(self.mu + c + hm + ah + da)), float(np.exp(self.mu + c + aa + dh))


def fit_global(df: pd.DataFrame, as_of: pd.Timestamp) -> Global | None:
    m = df[df["completed"] & (df["dt"] < as_of) & (df["dt"] >= as_of - pd.Timedelta(days=730))]
    if len(m) < 600:
        return None
    teams = sorted(set(m["home"]) | set(m["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    # championnat d'une équipe = celui où elle a le plus joué (hors coupes)
    dom = m[~m["slug"].isin(CUPS)]
    long = pd.concat([dom[["home", "slug"]].rename(columns={"home": "t"}), dom[["away", "slug"]].rename(columns={"away": "t"})])
    main = long.groupby("t")["slug"].agg(lambda s: s.value_counts().index[0])
    leagues = sorted(set(main.values)) + ["autre"]
    lidx = {l: i for i, l in enumerate(leagues)}
    tl = np.array([lidx.get(main.get(t, "autre"), lidx["autre"]) for t in teams])
    L = len(leagues)
    h = m["home"].map(idx).to_numpy()
    a = m["away"].map(idx).to_numpy()
    yh, ya = m["hg"].to_numpy(float), m["ag"].to_numpy(float)
    w = np.exp(-XI * (as_of - m["dt"]).dt.days.to_numpy(float))
    cup = m["slug"].isin(CUPS).to_numpy()
    w = np.where(cup, w * 2.0, w)  # les matchs européens pèsent double : ce sont eux qui relient les ligues
    cup_list = list(CUPS)
    comp = np.array([cup_list.index(sl) + 1 if sl in CUPS else 0 for sl in m["slug"]])
    K = len(cup_list) + 1

    def obj(x):
        mu, hm = x[0], x[1]
        att, dfn = x[2:2 + n], x[2 + n:2 + 2 * n]
        la_, ld_ = x[2 + 2 * n:2 + 2 * n + L], x[2 + 2 * n + L:2 + 2 * n + 2 * L]
        cm = np.concatenate([[0.0], x[2 + 2 * n + 2 * L:]])
        A, D = la_[tl] + att, ld_[tl] + dfn
        eh, ea = mu + cm[comp] + hm + A[h] + D[a], mu + cm[comp] + A[a] + D[h]
        lh, lav = np.exp(eh), np.exp(ea)
        nll = np.sum(w * (lh - yh * eh)) + np.sum(w * (lav - ya * ea))
        nll += RIDGE_TEAM * (att @ att + dfn @ dfn) + RIDGE_LEAGUE * (la_ @ la_ + ld_ @ ld_) + 0.5 * cm @ cm
        rh, ra = w * (lh - yh), w * (lav - ya)
        gA = np.bincount(h, rh, n) + np.bincount(a, ra, n)
        gD = np.bincount(a, rh, n) + np.bincount(h, ra, n)
        g = np.concatenate([[rh.sum() + ra.sum(), rh.sum()], gA + 2 * RIDGE_TEAM * att, gD + 2 * RIDGE_TEAM * dfn,
                            np.bincount(tl, gA, L) + 2 * RIDGE_LEAGUE * la_, np.bincount(tl, gD, L) + 2 * RIDGE_LEAGUE * ld_,
                            (np.bincount(comp, rh + ra, K) + 2 * 0.5 * cm)[1:]])
        return nll, g

    x0 = np.zeros(2 + 2 * n + 2 * L + K - 1)
    x0[0], x0[1] = np.log(1.3), 0.2
    x = minimize(obj, x0, jac=True, method="L-BFGS-B", options={"maxiter": 3000}).x
    g = Global(idx, tl, x[2:2 + n], x[2 + n:2 + 2 * n], x[2 + 2 * n:2 + 2 * n + L], x[2 + 2 * n + L:2 + 2 * n + 2 * L],
               float(x[0]), float(x[1]), -0.05, leagues, dict(zip(cup_list, x[2 + 2 * n + 2 * L:].tolist())))
    # Tendance de la saison en cours : si les coupes sont plus prolifiques ces 4 derniers mois que prévu,
    # on relève leur niveau de buts (avec prudence : 40 buts « fictifs » au prix du modèle)
    recent = m[cup & (m["dt"] >= as_of - pd.Timedelta(days=120))]
    for slug in cup_list:
        r = recent[recent["slug"] == slug]
        if len(r) < 10:
            continue
        pred = sum(sum(g.rates(a_, b_, slug=slug)) for a_, b_ in zip(r["home"], r["away"]))
        obs = float((r["hg"] + r["ag"]).sum())
        g.cup_mu[slug] += float(np.log((obs + 40) / (pred + 40)))
    return g


def match_id(dt: pd.Timestamp, code: str, home: str, away: str) -> str:
    return f"{dt.strftime('%Y%m%d')}|{code}|{home}|{away}"


def team_form(df, team, n=6):
    m = df[df["completed"] & ((df["home"] == team) | (df["away"] == team))].tail(n)
    games = []
    for r in m.itertuples():
        home = r.home == team
        games.append({"d": r.dt.strftime("%d/%m"), "opp": r.away if home else r.home, "h": home,
                      "gf": int(r.hg if home else r.ag), "ga": int(r.ag if home else r.hg)})
    tot = [g["gf"] + g["ga"] for g in games]
    return {"games": games, "avg_total": round(float(np.mean(tot)), 2) if tot else None,
            "o25_rate": round(float(np.mean([t >= 3 for t in tot])), 2) if tot else None}


def backtest(df: pd.DataFrame, today: pd.Timestamp) -> dict | None:
    """Matchs européens des 15 derniers mois, prédits avec un modèle ajusté avant chaque quinzaine."""
    from model import markets_from_total, score_matrix, total_dist
    # on ne juge le modèle que lorsqu'il dispose d'au moins 300 jours d'historique
    first = df.loc[df["completed"], "dt"].min()
    start = max(today - pd.Timedelta(days=450), first + pd.Timedelta(days=300))
    cups = df[df["completed"] & df["slug"].isin(CUPS) & (df["dt"] >= start)]
    if len(cups) < 60:
        return None
    preds, ys = [], []
    t = cups["dt"].min().normalize()
    while t < today:
        nxt = t + pd.Timedelta(days=14)
        block = cups[(cups["dt"] >= t) & (cups["dt"] < nxt)]
        if len(block):
            g = fit_global(df, t)
            if g is not None:
                for r in block.itertuples():
                    if g.known(r.home) and g.known(r.away):
                        lh, la = g.rates(r.home, r.away, slug=r.slug)
                        p = markets_from_total(total_dist(score_matrix(lh, la, g.rho)))
                        preds.append((p["o15"], p["o25"]))
                        ys.append(r.hg + r.ag)
        t = nxt
    if len(ys) < 50:
        return None
    p = np.array(preds)
    y = np.array(ys)
    out = {"n": len(y)}
    before = df[df["completed"] & df["slug"].isin(CUPS) & (df["dt"] < start)]
    tb = (before["hg"] + before["ag"]).to_numpy()
    for k, (j, thr) in {"o15": (0, 2), "o25": (1, 3)}.items():
        yy = (y >= thr).astype(float)
        # référence honnête : la fréquence observée AVANT la période de test
        base = np.full_like(yy, (tb >= thr).mean() if len(tb) else yy.mean())
        out[k] = {"rate": round(float(yy.mean()), 3), "pred": round(float(p[:, j].mean()), 3),
                  "brier": round(float(np.mean((p[:, j] - yy) ** 2)), 4), "brier_base": round(float(np.mean((base - yy) ** 2)), 4)}
    return out


def update(today: date, offline: bool = False):
    """Renvoie (matchs à venir au format de l'appli, scores joués, tableau des résultats, rapport de backtest)."""
    from model import markets_from_total, result_probs, score_matrix, total_dist
    if not offline:
        download(today)
    df = load()
    if df.empty:
        return [], {}, df, None
    now = pd.Timestamp(datetime.now(timezone.utc))
    g = fit_global(df, now)
    scores = {}
    for r in df[df["completed"] & df["slug"].isin(CUPS)].itertuples():
        scores[match_id(r.dt, CUPS[r.slug][0], r.home, r.away)] = (int(r.hg), int(r.ag))
    upcoming = []
    if g is not None:
        start = pd.Timestamp(today, tz="UTC")
        fx = df[(~df["completed"]) & df["slug"].isin(CUPS) & (df["dt"] >= start) & (df["dt"] < start + pd.Timedelta(days=7))]
        for r in fx.itertuples():
            if not (g.known(r.home) and g.known(r.away)):
                continue
            code, name = CUPS[r.slug]
            lh, la = g.rates(r.home, r.away, slug=r.slug)
            mat = score_matrix(lh, la, g.rho)
            final = markets_from_total(total_dist(mat))
            flat = sorted(((mat[i, j], i, j) for i in range(6) for j in range(6)), reverse=True)[:6]
            upcoming.append({
                "id": match_id(r.dt, code, r.home, r.away), "div": code, "league": name, "country": "Europe",
                "date": r.dt.strftime("%Y-%m-%d"), "time": r.dt.strftime("%H:%M"), "home": r.home, "away": r.away,
                "lh": lh, "la": la, "final": final, "res": result_probs(mat), "espn": [r.slug, r.espn_id],
                "top_scores": [{"s": f"{i}-{j}", "p": round(float(p), 3)} for p, i, j in flat],
                "total_dist": [round(float(x), 4) for x in total_dist(mat)[:7]],
                "form_home": team_form(df, r.home), "form_away": team_form(df, r.away),
            })
    done = df[df["completed"]]
    coverage = int((done["dt"].max() - done["dt"].min()).days) if len(done) else 0
    for u in upcoming:
        u["provisional"] = coverage < MIN_COVERAGE_DAYS
    return upcoming, scores, df, g
