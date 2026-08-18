"""
strategy.py — LES RÈGLES. C'est ici que tu interviens.

Stratégie de départ : breakout de canal de Donchian filtré par la tendance.
  - Entrée LONG  : le cours clôture au-dessus du plus-haut des N derniers jours
                   ET au-dessus de sa moyenne mobile longue (tendance haussière).
  - Entrée SHORT : symétrique à la baisse (ta "VAD").
  - Stop initial : distance = atr_mult * ATR (invalidation objective).
  - Sortie       : trailing stop de Donchian (canal de sortie plus court) —
                   on laisse courir tant que la tendance ne casse pas.

Pourquoi cette ossature ? Parce que c'est la traduction systématique la plus
fidèle de ce que ta formation fait à l'oeil : cassure de pivot + filtre de
tendance + stop + on laisse courir. Une fois que tu maîtrises les règles
exactes de la formation, tu ne modifies QUE les fonctions ci-dessous.

RÈGLE D'OR ANTI-BIAIS : tous les indicateurs utilisés pour décider à la
clôture du jour t sont calculés avec .shift(1), c.-à-d. qu'ils n'utilisent
QUE de l'information disponible à la clôture de t-1 pour définir le niveau à
casser. Le signal est ensuite exécuté à l'ouverture de t+1 (géré par engine.py).
Aucune information future ne fuite (pas de look-ahead bias).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    """Average True Range — mesure de volatilité pour dimensionner le stop."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def compute_signals(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """
    Enrichit le DataFrame d'un titre avec, pour CHAQUE barre :
      - signal      : +1 (entrée long), -1 (entrée short), 0 (rien)
      - stop_dist   : distance de stop initiale (en prix) si on entrait
      - exit_lo     : niveau du trailing stop pour une position longue
      - exit_hi     : niveau du trailing stop pour une position courte

    Ces colonnes sont "décalées" côté engine (exécution à t+1), donc elles
    peuvent utiliser la clôture de t en toute sécurité.
    """
    out = df.copy()

    # --- Canaux de Donchian (on exclut la barre courante via shift(1)) ---
    # Le plus-haut/plus-bas des N barres PRÉCÉDENTES : c'est le niveau à casser.
    dch_hi = out["High"].rolling(cfg.breakout_lookback).max().shift(1)
    dch_lo = out["Low"].rolling(cfg.breakout_lookback).min().shift(1)

    # --- Filtre de tendance ---
    ma = out["Close"].rolling(cfg.trend_ma).mean()

    # --- Volatilité pour le stop ---
    atr = _atr(out, cfg.atr_len)

    # --- Signaux d'ENTRÉE (à la clôture de la barre courante) ---
    long_entry = (out["Close"] > dch_hi) & (out["Close"] > ma)
    short_entry = (out["Close"] < dch_lo) & (out["Close"] < ma)

    signal = pd.Series(0, index=out.index, dtype=int)
    if cfg.allow_long:
        signal = signal.mask(long_entry, 1)
    if cfg.allow_short:
        signal = signal.mask(short_entry, -1)

    # --- Niveaux de SORTIE (trailing stop de Donchian, canal plus court) ---
    # Pour une position longue : on sort si on casse le plus-bas des M derniers
    # jours. Pour une position courte : le plus-haut des M derniers jours.
    exit_lo = out["Low"].rolling(cfg.exit_lookback).min().shift(1)
    exit_hi = out["High"].rolling(cfg.exit_lookback).max().shift(1)

    out["signal"] = signal
    out["stop_dist"] = atr * cfg.atr_mult
    out["exit_lo"] = exit_lo
    out["exit_hi"] = exit_hi
    out["atr"] = atr
    # Les niveaux à casser sont exposés pour que screener.py puisse mesurer la
    # DISTANCE à la cassure sans redéfinir la règle de son côté. Une seule
    # source de vérité : ce que le screener affiche est ce que le backtest teste.
    out["dch_hi"] = dch_hi
    out["dch_lo"] = dch_lo
    out["trend_ma"] = ma
    return out
