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
    # Ajoutés le 01/11/2026 pour suivre plus de matchs (mêmes paris, mêmes données gratuites, tous sur 1xBet).
    # Un championnat mal prédit au backtest est bloqué automatiquement (voir backtest.diagnostic).
    "E2": ("League One", "Angleterre"),
    "E3": ("League Two", "Angleterre"),
    "SC0": ("Premiership", "Écosse"),
    "D2": ("2. Bundesliga", "Allemagne"),
    "I2": ("Serie B", "Italie"),
    "F2": ("Ligue 2", "France"),
    "B1": ("Pro League", "Belgique"),
    "G1": ("Super League", "Grèce"),
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
MARKETS = {"o15": "Plus de 1,5 but", "o20": "Plus de 2 buts", "o25": "Plus de 2,5 buts"}  # autres paris : extra.LABELS

# Marge supposée du bookmaker sur les totaux (sert à estimer la cote 1xBet quand on ne l'a pas)
BOOK_MARGIN = 0.06

# Règle d'Est (31/10/2026) : plus de +2,5 dans les coupons, c'est lui qui les faisait casser (70 % des pertes
# des coupons buts sur 3 ans). Le +2 asiatique, remboursé à 2 buts, prend sa place.
COUPON_EXCLUDED = {"o25"}

# Début du suivi réel (demande d'Est le 31/10/2026, après le nouveau paramétrage) : tout ce qui est
# antérieur est archivé dans data/state/archive/ et ne compte plus dans le suivi ni dans l'apprentissage
TRACKING_START = "2026-11-01"

# Taxe sur les gains au Sénégal : 20 % du gain net. Une cote 2 ne rapporte que 1 + (2 - 1) × 0,8 = 1,80.
TAX = 0.20


def gross_odds(net: float) -> float:
    """Cote affichée nécessaire pour toucher `net` après taxe."""
    return round(1 + (net - 1) / (1 - TAX), 2)


# Coupons. Règle d'Est : les coupons sûrs, par championnat et favoris ne dépassent pas 2 net après taxe
# (cote affichée entre 2,00 et 2,25) ; les autres visent au moins 2 net.
COUPONS = {
    # stake_pct : mise conseillée en % de la bankroll (priorité aux petits gains réguliers)
    "sur": {"label": "Coupon sûr", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (2, 3), "stake_pct": 2.0},
    "ligue": {"label": "Coupon championnat", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (2, 3), "stake_pct": 1.5},
    "favoris": {"label": "Ticket favoris", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (2, 4), "stake_pct": 2.0},
    "buts15": {"label": "Coupon +1,5", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (3, 5), "stake_pct": 1.5},
    "buts20": {"label": "Coupon +2 (remboursé à 2 buts)", "min_odds": 2.0, "max_odds": 4.0, "legs": (2, 4), "stake_pct": 1.0},
    "mix": {"label": "Coupon mix", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (2, 3), "stake_pct": 1.5},
    "dc": {"label": "Double chance", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (3, 6), "stake_pct": 1.5},
    "autres": {"label": "Autres paris", "min_odds": 2.0, "max_odds": gross_odds(2.0), "legs": (2, 5), "stake_pct": 1.0},
    "periode_buts": {"label": "Buts sur la période", "min_odds": gross_odds(2.0), "max_odds": 3.5, "legs": (3, 5), "stake_pct": 1.0},
    "periode_fav": {"label": "Favoris sur la période", "min_odds": gross_odds(2.0), "max_odds": 3.5, "legs": (3, 5), "stake_pct": 1.0},
    "large3": {"label": "Ticket large · cote 3 à 5", "min_odds": 3.0, "max_odds": 5.0, "legs": (2, 5), "stake_pct": 0.5},
    "large5": {"label": "Ticket large · cote 5 à 8", "min_odds": 5.0, "max_odds": 8.0, "legs": (3, 6), "stake_pct": 0.5},
    "relais": {"label": "Relais (protège un ticket)", "min_odds": 2.0, "max_odds": 1e9, "legs": (2, 22), "stake_pct": 0.5},
    "periode_long": {"label": "Combiné longue durée", "min_odds": 3.0, "max_odds": 1e9, "legs": (3, 22), "stake_pct": 0.5},
    "tendance": {"label": "Coupon tendances", "min_odds": 2.0, "max_odds": 3.0, "legs": (3, 4), "stake_pct": 1.0},
    "value": {"label": "Coupon value", "min_odds": gross_odds(2.0), "max_odds": 4.0, "legs": (2, 3), "stake_pct": 1.0},
    "audace": {"label": "Coupon audacieux", "min_odds": 4.0, "max_odds": 9.0, "legs": (3, 4), "stake_pct": 0.5},
    "mille": {"label": "Cote 1000", "min_odds": 1000.0, "max_odds": 1e9, "legs": (8, 22), "stake_pct": 0.1},
    "jackpot_fiable": {"label": "Jackpot fiable", "min_odds": 10.0, "max_odds": 1e9, "legs": (3, 15), "stake_pct": 0.25},
    "jackpot": {"label": "Jackpot", "min_odds": 15.0, "max_odds": 1e9, "legs": (6, 8), "stake_pct": 0.25},
}
VALUE_EDGE = 0.03       # avantage minimum pour une sélection « value »
MIN_LEG_ODDS = 1.12     # en dessous, la sélection n'apporte rien au coupon
# Chance minimale (gagné ou remboursé) de chaque sélection, par type de coupon : réglée sur le test du passé
MIN_LEG_P: dict = {}  # testé de 0,65 à 0,80 : aucun gain de réussite, la cote 2 impose la même chance quelle que soit la sélection
# Coupons sûrs et championnat à 2-3 matchs : la marge du bookmaker se paie à chaque sélection,
# test 2023-2026 : 46 % de réussite à 2 matchs contre 43 % à 3-4 matchs, pour la même cote
# Un même match peut revenir dans plusieurs coupons du jour, mais jamais sur la même sélection :
# un autre marché qui protège (+1,5 d'un côté, +2,5 de l'autre, ou victoire du favori), et au plus 3 fois
MAX_COUPONS_PER_MATCH = 3

# Nombre de coupons par jour : pas de limite fixe, on garde tous ceux qui passent ces seuils
MIN_P = {"large3": 0.2, "large5": 0.12, "dc": 0.36, "autres": 0.36, "buts15": 0.36, "buts20": 0.3, "mix": 0.36, "tendance": 0.3, "sur": 0.36, "ligue": 0.34, "value": 0.25, "audace": 0.15, "favoris": 0.36, "periode_buts": 0.3, "periode_fav": 0.3}
MAX_PER_DAY = {"large3": 4, "large5": 3, "dc": 4, "autres": 6, "buts15": 4, "buts20": 3, "mix": 6, "tendance": 2, "sur": 8, "ligue": 10, "value": 4, "audace": 3, "jackpot": 1, "favoris": 4, "periode_buts": 1, "periode_fav": 1}

# Tickets sur une période (en jours), créés chaque jour
PERIODS = {5: "5 jours", 7: "1 semaine", 15: "15 jours", 21: "3 semaines", 30: "1 mois"}
# Combinés longue durée : +1,5, +2 et gros favoris uniquement, pour viser ces cotes sur ces périodes
LONG_PERIODS = {7: "1 semaine", 15: "15 jours", 30: "1 mois"}
LONG_TARGETS = (3.0, 5.0, 10.0, 20.0, 50.0, 100.0)
