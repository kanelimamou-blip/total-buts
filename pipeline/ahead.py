"""Calendrier à un mois pour les 10 championnats (source ESPN, gratuite).

football-data.co.uk ne publie les matchs à venir (avec cotes) que quelques jours avant.
On complète avec le calendrier ESPN, en traduisant les noms d'équipes ESPN vers ceux
de football-data grâce aux matchs déjà joués : même jour, même score = même match.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta

import pandas as pd

import europe
from config import RAW_DIR

FD_TO_ESPN = {"E0": "eng.1", "E1": "eng.2", "F1": "fra.1", "I1": "ita.1", "SP1": "esp.1", "SP2": "esp.2",
              "D1": "ger.1", "P1": "por.1", "T1": "tur.1", "N1": "ned.1"}
CACHE = RAW_DIR / "espn_ahead"
PAST_DAYS = 45
AHEAD_DAYS = 30


def download(today: date) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for div, slug in FD_TO_ESPN.items():
        for k in range(-PAST_DAYS, AHEAD_DAYS + 1):
            d = today + timedelta(days=k)
            path = CACHE / f"{slug}_{d:%Y%m%d}.json"
            if path.exists() and k < -4:
                continue
            rows = europe._fetch(slug, d, 1)
            if rows is not None:
                path.write_text(json.dumps(rows))


def _load() -> pd.DataFrame:
    rows = []
    for p in CACHE.glob("*.json"):
        try:
            rows += json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates("espn_id", keep="last")
    df["dt"] = pd.to_datetime(df["dt"], utc=True)
    return df


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|cf|afc|sc|ac|as|ss|sv|vfb|vfl|fk|sk|ud|cd|rc|sd|club|de|calcio|1\.)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def name_map(espn: pd.DataFrame, results: pd.DataFrame) -> dict:
    """Noms ESPN -> noms football-data, par championnat."""
    out = {}
    for div, slug in FD_TO_ESPN.items():
        e = espn[(espn["slug"] == slug) & espn["completed"]]
        r = results[results["div"] == div]
        fd_teams = sorted(set(r[r["date"] >= r["date"].max() - pd.Timedelta(days=400)][["home", "away"]].stack()))
        votes = {}
        if len(e) and len(r):
            r_by = {}
            for row in r.itertuples():
                r_by.setdefault((row.date.date(), row.hg, row.ag), []).append(row)
            for row in e.itertuples():
                d = row.dt.date()
                cands = []
                for dd in (d, d - timedelta(days=1), d + timedelta(days=1)):
                    cands += r_by.get((dd, row.hg, row.ag), [])
                if len(cands) == 1:
                    votes.setdefault(row.home, Counter())[cands[0].home] += 1
                    votes.setdefault(row.away, Counter())[cands[0].away] += 1
        m = {k: c.most_common(1)[0][0] for k, c in votes.items() if c.most_common(1)[0][1] >= 2}
        used = set(m.values())
        free = [t for t in fd_teams if t not in used]
        for name in sorted(set(espn[espn["slug"] == slug][["home", "away"]].stack()) - set(m)):
            best = difflib.get_close_matches(_norm(name), [_norm(t) for t in free], n=1, cutoff=0.55)
            if best:
                t = free[[_norm(x) for x in free].index(best[0])]
                m[name] = t
                free.remove(t)
        out[div] = m
    return out


def fixtures(today: date, results: pd.DataFrame, offline: bool = False) -> pd.DataFrame:
    """Matchs à venir sur AHEAD_DAYS jours, au format de fetch.load_fixtures (sans cotes)."""
    if not offline:
        download(today)
    espn = _load()
    cols = ["div", "date", "time", "home", "away", "o25", "u25", "oh", "od", "oa", "slug", "espn_id"]
    if espn.empty:
        return pd.DataFrame(columns=cols)
    names = name_map(espn, results)
    rev = {slug: div for div, slug in FD_TO_ESPN.items()}
    up = espn[(~espn["completed"]) & (espn["dt"] >= pd.Timestamp(today, tz="UTC"))]
    rows = []
    for r in up.itertuples():
        div = rev.get(r.slug)
        m = names.get(div, {})
        if div is None or r.home not in m or r.away not in m:
            continue
        rows.append({"div": div, "date": pd.Timestamp(r.dt.date()), "time": r.dt.strftime("%H:%M"),
                     "home": m[r.home], "away": m[r.away], "o25": float("nan"), "u25": float("nan"),
                     "oh": float("nan"), "od": float("nan"), "oa": float("nan"), "slug": r.slug, "espn_id": r.espn_id})
    return pd.DataFrame(rows, columns=cols)
