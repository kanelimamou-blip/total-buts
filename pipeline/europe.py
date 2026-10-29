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
DOMESTIC = ["eng.1", "eng.2", "esp.1", "esp.2", "fra.1", "ita.1", "ger.1", "por.1", "tur.1", "ned.1",
            "bel.1", "sco.1", "aut.1", "sui.1", "gre.1", "den.1", "cze.1", "nor.1", "swe.1", "pol.1",
            "cro.1", "srb.1", "ukr.1", "isr.1", "cyp.1", "hun.1", "rou.1", "bul.1", "svk.1", "svn.1",
            "ger.2", "fra.2", "ita.2", "rus.1", "kaz.1", "aze.1", "irl.1", "fin.1", "isl.1", "mda.1"]
CACHE = RAW_DIR / "espn"
HISTORY_MONTHS = 26
RIDGE_TEAM = 3.0
RIDGE_LEAGUE = 0.3


STATUS: dict = {}


VARIANTS = [{"limit": 1000}, {"limit": 500}, {"limit": 200}, {}]
_variant = {"i": None}


def _get(url, params):
    """Essaie les formats de requête connus et retient le premier accepté."""
    order = [_variant["i"]] if _variant["i"] is not None else range(len(VARIANTS))
    for i in order:
        p = {k: v for k, v in params.items() if k != "limit"} | VARIANTS[i]
        out = _get_once(url, p)
        if out is not None:
            _variant["i"] = i
            STATUS["_variant"] = VARIANTS[i]
            return out
    return None


def _get_once(url, params):
    key = url.split("/soccer/")[1].split("/")[0]
    st = STATUS.setdefault(key, {"ok": 0, "fail": 0, "last": None})
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "Mozilla/5.0 (total-buts)"})
            st["last"] = r.status_code
            if r.status_code in (400, 404):
                st["fail"] += 1
                st["body"] = r.text[:200]
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
            if row["completed"]:
                row["hg"], row["ag"] = int(float(teams["home"]["score"])), int(float(teams["away"]["score"]))
            rows.append(row)
        except (KeyError, ValueError, TypeError, IndexError):
            continue
    return rows


def _month_ranges(today: date):
    first = date(today.year, today.month, 1)
    out = []
    for k in range(HISTORY_MONTHS, -1, -1):
        y, m = first.year, first.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        start = date(y, m, 1)
        end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        out.append((start, end))
    return out


def probe(today: date) -> dict:
    """Teste quelques formats de requête et garde la réponse, pour diagnostic."""
    out = {}
    d0, d1 = today - timedelta(days=30), today
    tests = {
        "range_limit": ({"dates": f"{d0:%Y%m%d}-{d1:%Y%m%d}", "limit": 1000}, ESPN),
        "range": ({"dates": f"{d0:%Y%m%d}-{d1:%Y%m%d}"}, ESPN),
        "day": ({"dates": f"{d1 - timedelta(days=8):%Y%m%d}"}, ESPN),
        "none": ({}, ESPN),
        "web_range": ({"dates": f"{d0:%Y%m%d}-{d1:%Y%m%d}", "limit": 1000},
                      "https://site.web.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"),
    }
    for name, (params, base) in tests.items():
        try:
            r = requests.get(base.format(slug="uefa.champions"), params=params, timeout=30,
                             headers={"User-Agent": "Mozilla/5.0 (total-buts)"})
            n = len(r.json().get("events", [])) if r.ok else None
            out[name] = {"status": r.status_code, "events": n, "body": r.text[:300] if not r.ok else ""}
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": str(exc)[:200]}
    return out


def download(today: date) -> None:
    """Mois terminés : téléchargés une fois. Mois en cours et précédent : à chaque passage."""
    CACHE.mkdir(parents=True, exist_ok=True)
    STATUS["_probe"] = probe(today)
    (RAW_DIR.parent / "state").mkdir(parents=True, exist_ok=True)
    (RAW_DIR.parent / "state" / "europe_status.json").write_text(json.dumps(STATUS, indent=1))
    if not any(v.get("events") for v in STATUS["_probe"].values()):
        return
    ranges = _month_ranges(today)
    recent = {r[0] for r in ranges[-2:]}
    for slug in list(CUPS) + DOMESTIC:
        for start, end in ranges:
            path = CACHE / f"{slug}_{start:%Y%m}.json"
            if path.exists() and start not in recent:
                continue
            data = _get(ESPN.format(slug=slug), {"dates": f"{start:%Y%m%d}-{end:%Y%m%d}", "limit": 1000})
            if data is not None:
                path.write_text(json.dumps(_parse(data, slug)))
        # semaine à venir (peut chevaucher le mois suivant)
        path = CACHE / f"{slug}_next.json"
        data = _get(ESPN.format(slug=slug), {"dates": f"{today:%Y%m%d}-{today + timedelta(days=8):%Y%m%d}", "limit": 1000})
        if data is not None:
            path.write_text(json.dumps(_parse(data, slug)))
    (RAW_DIR.parent / "state").mkdir(parents=True, exist_ok=True)
    (RAW_DIR.parent / "state" / "europe_status.json").write_text(json.dumps(STATUS, indent=1))


def load() -> pd.DataFrame:
    rows = []
    for p in sorted(CACHE.glob("*.json")):
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
    def __init__(self, teams, team_league, att, dfn, latt, ldef, mu, home, rho, leagues):
        self.teams, self.team_league = teams, team_league
        self.att, self.dfn, self.latt, self.ldef = att, dfn, latt, ldef
        self.mu, self.home, self.rho, self.leagues = mu, home, rho, leagues

    def known(self, t):
        return t in self.teams

    def _ad(self, t):
        i = self.teams[t]
        l = self.team_league[i]
        return self.latt[l] + self.att[i], self.ldef[l] + self.dfn[i]

    def rates(self, home, away, neutral=False):
        ah, dh = self._ad(home)
        aa, da = self._ad(away)
        hm = 0.0 if neutral else self.home
        return float(np.exp(self.mu + hm + ah + da)), float(np.exp(self.mu + aa + dh))


def fit_global(df: pd.DataFrame, as_of: pd.Timestamp) -> Global | None:
    m = df[df["completed"] & (df["dt"] < as_of) & (df["dt"] >= as_of - pd.Timedelta(days=730))]
    if len(m) < 1000:
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

    def obj(x):
        mu, hm = x[0], x[1]
        att, dfn = x[2:2 + n], x[2 + n:2 + 2 * n]
        la_, ld_ = x[2 + 2 * n:2 + 2 * n + L], x[2 + 2 * n + L:]
        A, D = la_[tl] + att, ld_[tl] + dfn
        eh, ea = mu + hm + A[h] + D[a], mu + A[a] + D[h]
        lh, lav = np.exp(eh), np.exp(ea)
        nll = np.sum(w * (lh - yh * eh)) + np.sum(w * (lav - ya * ea))
        nll += RIDGE_TEAM * (att @ att + dfn @ dfn) + RIDGE_LEAGUE * (la_ @ la_ + ld_ @ ld_)
        rh, ra = w * (lh - yh), w * (lav - ya)
        gA = np.bincount(h, rh, n) + np.bincount(a, ra, n)
        gD = np.bincount(a, rh, n) + np.bincount(h, ra, n)
        g = np.concatenate([[rh.sum() + ra.sum(), rh.sum()], gA + 2 * RIDGE_TEAM * att, gD + 2 * RIDGE_TEAM * dfn,
                            np.bincount(tl, gA, L) + 2 * RIDGE_LEAGUE * la_, np.bincount(tl, gD, L) + 2 * RIDGE_LEAGUE * ld_])
        return nll, g

    x0 = np.zeros(2 + 2 * n + 2 * L)
    x0[0], x0[1] = np.log(1.3), 0.2
    x = minimize(obj, x0, jac=True, method="L-BFGS-B", options={"maxiter": 3000}).x
    return Global(idx, tl, x[2:2 + n], x[2 + n:2 + 2 * n], x[2 + 2 * n:2 + 2 * n + L], x[2 + 2 * n + L:],
                  float(x[0]), float(x[1]), -0.05, leagues)


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
    cups = df[df["completed"] & df["slug"].isin(CUPS) & (df["dt"] >= today - pd.Timedelta(days=450))]
    if len(cups) < 100:
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
                        lh, la = g.rates(r.home, r.away)
                        p = markets_from_total(total_dist(score_matrix(lh, la, g.rho)))
                        preds.append((p["o15"], p["o25"]))
                        ys.append(r.hg + r.ag)
        t = nxt
    if len(ys) < 50:
        return None
    p = np.array(preds)
    y = np.array(ys)
    out = {"n": len(y)}
    for k, (j, thr) in {"o15": (0, 2), "o25": (1, 3)}.items():
        yy = (y >= thr).astype(float)
        base = np.full_like(yy, yy.mean())
        out[k] = {"rate": round(float(yy.mean()), 3), "pred": round(float(p[:, j].mean()), 3),
                  "brier": round(float(np.mean((p[:, j] - yy) ** 2)), 4), "brier_base": round(float(np.mean((base - yy) ** 2)), 4)}
    return out


def update(today: date, offline: bool = False):
    """Renvoie (matchs à venir au format de l'appli, scores joués, tableau des résultats, rapport de backtest)."""
    from model import markets_from_total, score_matrix, total_dist
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
            lh, la = g.rates(r.home, r.away)
            mat = score_matrix(lh, la, g.rho)
            final = markets_from_total(total_dist(mat))
            flat = sorted(((mat[i, j], i, j) for i in range(6) for j in range(6)), reverse=True)[:6]
            upcoming.append({
                "id": match_id(r.dt, code, r.home, r.away), "div": code, "league": name, "country": "Europe",
                "date": r.dt.strftime("%Y-%m-%d"), "time": r.dt.strftime("%H:%M"), "home": r.home, "away": r.away,
                "lh": lh, "la": la, "final": final,
                "top_scores": [{"s": f"{i}-{j}", "p": round(float(p), 3)} for p, i, j in flat],
                "total_dist": [round(float(x), 4) for x in total_dist(mat)[:7]],
                "form_home": team_form(df, r.home), "form_away": team_form(df, r.away),
            })
    return upcoming, scores, df, g
