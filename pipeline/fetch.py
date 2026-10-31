"""Téléchargement et normalisation des données football-data.co.uk."""
from __future__ import annotations

import io
import time
from datetime import date

import pandas as pd
import requests

from config import BASE_URL, LEAGUES, N_SEASONS, RAW_DIR

COLS = {
    "o25": ["Avg>2.5", "BbAv>2.5", "B365>2.5", "P>2.5"],
    "u25": ["Avg<2.5", "BbAv<2.5", "B365<2.5", "P<2.5"],
    "o25_max": ["Max>2.5", "BbMx>2.5"],
    "o25_close": ["AvgC>2.5", "PC>2.5", "B365C>2.5"],
    "u25_close": ["AvgC<2.5", "PC<2.5", "B365C<2.5"],
    "oh": ["AvgH", "BbAvH", "B365H", "PSH"],
    "od": ["AvgD", "BbAvD", "B365D", "PSD"],
    "oa": ["AvgA", "BbAvA", "B365A", "PSA"],
    "hs": ["HS"], "as_": ["AS"], "hst": ["HST"], "ast": ["AST"],
    "hthg": ["HTHG"], "htag": ["HTAG"],
}


def season_code(d: date) -> str:
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def recent_seasons(today: date, n: int = N_SEASONS) -> list[str]:
    y = today.year if today.month >= 7 else today.year - 1
    return [f"{(y - k) % 100:02d}{(y - k + 1) % 100:02d}" for k in range(n - 1, -1, -1)]


def _get(url: str) -> bytes | None:
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "total-buts/1.0"})
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            time.sleep(2 ** attempt)
    return None


def download(today: date, refresh_current: bool = True) -> None:
    """Saisons terminées : téléchargées une fois. Saison en cours : à chaque passage."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    current = season_code(today)
    for season in recent_seasons(today):
        for div in LEAGUES:
            path = RAW_DIR / f"{season}_{div}.csv"
            if path.exists() and not (refresh_current and season == current):
                continue
            content = _get(f"{BASE_URL}/mmz4281/{season}/{div}.csv")
            if content:
                path.write_bytes(content)
    content = _get(f"{BASE_URL}/fixtures.csv")
    if content:
        (RAW_DIR / "fixtures.csv").write_bytes(content)


def _first(df: pd.DataFrame, names: list[str]) -> pd.Series:
    out = pd.Series(float("nan"), index=df.index)
    for n in names:
        if n in df.columns:
            out = out.fillna(pd.to_numeric(df[n], errors="coerce"))
    return out


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().lstrip("﻿") for c in df.columns]
    if "HomeTeam" not in df.columns and "Home" in df.columns:
        df = df.rename(columns={"Home": "HomeTeam", "Away": "AwayTeam", "HG": "FTHG", "AG": "FTAG"})
    df = df.dropna(subset=["Div", "HomeTeam", "AwayTeam", "Date"])
    out = pd.DataFrame({
        "div": df["Div"].astype(str).str.strip(),
        "date": pd.to_datetime(df["Date"], dayfirst=True, errors="coerce"),
        "time": df["Time"].astype(str).str.strip() if "Time" in df.columns else "",
        "home": df["HomeTeam"].astype(str).str.strip(),
        "away": df["AwayTeam"].astype(str).str.strip(),
        "hg": pd.to_numeric(df.get("FTHG"), errors="coerce"),
        "ag": pd.to_numeric(df.get("FTAG"), errors="coerce"),
    })
    for key, names in COLS.items():
        out[key] = _first(df, names)
    out["time"] = out["time"].replace({"nan": ""})
    return out.dropna(subset=["date"])


def _read_csv(raw: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc, on_bad_lines="skip")
        except UnicodeDecodeError:
            continue
    return pd.DataFrame()


def load_results() -> pd.DataFrame:
    frames = []
    for path in sorted(RAW_DIR.glob("*_*.csv")):
        df = _read_csv(path.read_bytes())
        if df.empty or "Div" not in df.columns:
            continue
        frames.append(_normalise(df))
    res = pd.concat(frames, ignore_index=True)
    res = res[res["div"].isin(LEAGUES)].dropna(subset=["hg", "ag"])
    res[["hg", "ag"]] = res[["hg", "ag"]].astype(int)
    return res.drop_duplicates(["div", "date", "home", "away"]).sort_values("date").reset_index(drop=True)


def load_fixtures() -> pd.DataFrame:
    path = RAW_DIR / "fixtures.csv"
    if not path.exists():
        return pd.DataFrame(columns=["div", "date", "time", "home", "away", "o25", "u25"])
    df = _read_csv(path.read_bytes())
    if df.empty or "Div" not in df.columns:
        return pd.DataFrame(columns=["div", "date", "time", "home", "away", "o25", "u25"])
    fx = _normalise(df)
    return fx[fx["div"].isin(LEAGUES)].reset_index(drop=True)
