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

# Taxe sur les gains au Sénégal : 20 % du gain net. Une cote 2 ne rapporte que 1 + (2 - 1) × 0,8 = 1,80.
TAX = 0.20


def gross_odds(net: float) -> float:
    """Cote affichée nécessaire pour toucher `net` après taxe."""
    return round(1 + (net - 1) / (1 - TAX), 2)


# Coupons. Règle d'Est : les coupons sûrs, par championnat et favoris ne dépassent pas 2 net après taxe
# (cote affichée entre 2,00 et 2,25) ; les autres visent au moins 2 net.
COUPONS = {
    # stake_pct : mise conseillée en % de la bankroll (priorité aux petits gains réguliers)
    "sur": {"label": "Coupon sûr", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (3, 4), "stake_pct": 2.0},
    "ligue": {"label": "Coupon championnat", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (3, 4), "stake_pct": 1.5},
    "favoris": {"label": "Ticket favoris", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (3, 4), "stake_pct": 2.0},
    "periode_buts": {"label": "Buts sur la période", "min_odds": gross_odds(2.0), "max_odds": 3.5, "legs": (3, 5), "stake_pct": 1.0},
    "periode_fav": {"label": "Favoris sur la période", "min_odds": gross_odds(2.0), "max_odds": 3.5, "legs": (3, 5), "stake_pct": 1.0},
    "value": {"label": "Coupon value", "min_odds": gross_odds(2.0), "max_odds": 4.0, "legs": (2, 3), "stake_pct": 1.0},
    "audace": {"label": "Coupon audacieux", "min_odds": 4.0, "max_odds": 9.0, "legs": (3, 4), "stake_pct": 0.5},
    "mille": {"label": "Cote 1000", "min_odds": 1000.0, "max_odds": 1e9, "legs": (8, 22), "stake_pct": 0.1},
    "jackpot": {"label": "Jackpot", "min_odds": 15.0, "max_odds": 1e9, "legs": (6, 8), "stake_pct": 0.25},
}
VALUE_EDGE = 0.03       # avantage minimum pour une sélection « value »
MIN_LEG_ODDS = 1.12     # en dessous, la sélection n'apporte rien au coupon

# Nombre de coupons par jour : pas de limite fixe, on garde tous ceux qui passent ces seuils
MIN_P = {"sur": 0.36, "ligue": 0.34, "value": 0.25, "audace": 0.15, "favoris": 0.36, "periode_buts": 0.3, "periode_fav": 0.3}
MAX_PER_DAY = {"sur": 8, "ligue": 10, "value": 4, "audace": 3, "jackpot": 1, "favoris": 4, "periode_buts": 1, "periode_fav": 1}

# Tickets sur une période (en jours), créés chaque jour
PERIODS = {5: "5 jours", 7: "1 semaine", 15: "15 jours", 21: "3 semaines", 30: "1 mois"}
