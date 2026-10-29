"""Réglages communs : ligues suivies, saisons, paramètres du modèle et des coupons."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
STATE_DIR = ROOT / "data" / "state"
SITE_DATA = ROOT / "docs" / "data"

BASE_URL = "https://www.football-data.co.uk"

# Code football-data.co.uk -> (nom affiché, pays)
LEAGUES = {
    "E0": ("Premier League", "Angleterre"),
    "E1": ("Championship", "Angleterre"),
    "F1": ("Ligue 1", "France"),
    "I1": ("Serie A", "Italie"),
    "SP1": ("LaLiga", "Espagne"),
    "SP2": ("LaLiga 2", "Espagne"),
    "D1": ("Bundesliga", "Allemagne"),
    "P1": ("Liga Portugal", "Portugal"),
    "T1": ("Süper Lig", "Turquie"),
    "N1": ("Eredivisie", "Pays-Bas"),
}

# Coupes d'Europe (données ESPN, voir europe.py)
CUPS = {
    "UCL": ("Ligue des Champions", "Europe"),
    "UEL": ("Ligue Europa", "Europe"),
    "UECL": ("Conference League", "Europe"),
}
ALL_COMPETITIONS = {**LEAGUES, **CUPS}

# Nombre de saisons d'historique téléchargées (saison en cours incluse)
N_SEASONS = 8

# Modèle Dixon-Coles
XI = 0.0019            # décroissance temporelle par jour (demi-vie ~ 1 an)
TRAIN_DAYS = 3 * 365   # fenêtre d'entraînement
RIDGE = 2.0            # rappel des notes d'équipe vers la moyenne
MAX_GOALS = 10

# Marchés suivis : clé -> libellé
MARKETS = {"o15": "Plus de 1,5 but", "o20": "Plus de 2 buts", "o25": "Plus de 2,5 buts"}

# Marge supposée du bookmaker sur les totaux (sert à estimer la cote 1xBet quand on ne l'a pas)
BOOK_MARGIN = 0.06

# Coupons
COUPONS = {
    # stake_pct : mise conseillée en % de la bankroll (priorité aux petits gains réguliers)
    "sur": {"label": "Coupon sûr", "min_odds": 2.0, "max_odds": 3.0, "legs": (3, 4), "stake_pct": 2.0},
    "ligue": {"label": "Coupon championnat", "min_odds": 2.0, "max_odds": 3.2, "legs": (3, 4), "stake_pct": 1.5},
    "value": {"label": "Coupon value", "min_odds": 2.0, "max_odds": 4.0, "legs": (2, 3), "stake_pct": 1.0},
    "audace": {"label": "Coupon audacieux", "min_odds": 4.0, "max_odds": 9.0, "legs": (3, 4), "stake_pct": 0.5},
    "jackpot": {"label": "Jackpot", "min_odds": 15.0, "max_odds": 1e9, "legs": (6, 8), "stake_pct": 0.25},
}
VALUE_EDGE = 0.03       # avantage minimum pour une sélection « value »
MIN_LEG_ODDS = 1.12     # en dessous, la sélection n'apporte rien au coupon

# Nombre de coupons par jour : pas de limite fixe, on garde tous ceux qui passent ces seuils
MIN_P = {"sur": 0.36, "ligue": 0.34, "value": 0.25, "audace": 0.15}
MAX_PER_DAY = {"sur": 8, "ligue": 10, "value": 4, "audace": 3, "jackpot": 1}
