"""
config.py — Tous les paramètres du backtest au même endroit.

C'est LE fichier que tu ajusteras au fur et à mesure de ta formation.
Le moteur (engine.py) et les métriques (metrics.py) n'ont PAS besoin d'être
touchés : ils sont "corrects par construction". Tu ne changes ici que les
règles de la stratégie et les hypothèses de coûts / risque.

Chaque paramètre est commenté avec :
  - ce qu'il fait
  - pourquoi il compte méthodologiquement
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    # ------------------------------------------------------------------ #
    #  PÉRIODE & UNIVERS                                                   #
    # ------------------------------------------------------------------ #
    start: str = "2010-01-01"
    end: str = "2024-12-31"

    # Univers de test. yfinance = constituants ACTUELS d'un indice
    # => biais du survivant (survivorship bias) : les boîtes faillies /
    # sorties de cote ont disparu de la liste, ce qui gonfle artificiellement
    # la performance. On l'assume et on le DOCUMENTE (cf. README). Pour un
    # vrai desk il faudrait un univers point-in-time (CRSP, Compustat...).
    universe: List[str] = field(default_factory=lambda: [
        # Large caps US liquides — juste un échantillon de départ.
        "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA",
        "JPM", "JNJ", "V", "PG", "XOM", "HD", "KO", "DIS",
        "NFLX", "ADBE", "CRM", "PEP", "CSCO",
    ])
    benchmark: str = "SPY"          # buy & hold de référence

    # ------------------------------------------------------------------ #
    #  RÈGLES DE STRATÉGIE  (breakout / suivi de tendance)                #
    #  --> le coeur de ce que tu vas affiner avec ta formation.           #
    # ------------------------------------------------------------------ #
    # Entrée : cassure (breakout) du plus-haut des N derniers jours,
    # filtrée par la tendance de fond (prix au-dessus de sa moyenne longue).
    # C'est l'ossature systématique la plus proche de ce que tu apprends
    # (pivots, cassures, VAD à la baisse, filtre de tendance).
    breakout_lookback: int = 55     # N : fenêtre de la cassure (canal de Donchian)
    trend_ma: int = 200             # filtre de tendance (moyenne mobile longue)
    exit_lookback: int = 20         # canal de sortie (trailing stop de Donchian)

    allow_long: bool = True         # achats
    allow_short: bool = True        # ventes à découvert (VAD)

    # ------------------------------------------------------------------ #
    #  RISQUE & SIZING  (le fameux "R" de ta formation)                   #
    # ------------------------------------------------------------------ #
    # Stop initial = atr_mult * ATR(atr_len). C'est la distance d'invalidation.
    atr_len: int = 20
    atr_mult: float = 3.0

    # On risque une fraction FIXE du capital courant par trade => 1 "R".
    # Sizing : nb d'actions = (risk_per_trade * equity) / (distance au stop).
    # C'est exactement la logique "money management en R" de la formation,
    # mais appliquée mécaniquement.
    risk_per_trade: float = 0.01    # 1 % du capital risqué par position

    max_positions: int = 10         # nb max de positions simultanées
    max_weight: float = 0.20        # notional max d'une position (20 % de l'equity)
    max_gross: float = 1.0          # exposition brute max (1.0 = pas de levier)

    # ------------------------------------------------------------------ #
    #  COÛTS DE TRANSACTION  (sans ça, un backtest est un mensonge)       #
    # ------------------------------------------------------------------ #
    commission_bps: float = 1.0     # commission courtier, en points de base
    slippage_bps: float = 5.0       # glissement (spread + impact), en bps
    #   1 bp = 0.01 %. Appliqués à l'entrée ET à la sortie.

    # ------------------------------------------------------------------ #
    #  CAPITAL & DIVERS                                                    #
    # ------------------------------------------------------------------ #
    initial_capital: float = 100_000.0
    ann_factor: int = 252           # jours de bourse par an (annualisation)
    risk_free: float = 0.0          # taux sans risque annualisé pour le Sharpe

    # Découpe in-sample / out-of-sample. On OPTIMISE (mentalement) sur l'IS
    # et on JUGE sur l'OOS, jamais l'inverse. Ici c'est juste une date de
    # coupure affichée dans le rapport pour t'entraîner à ce réflexe.
    oos_start: str = "2020-01-01"


CONFIG = Config()
