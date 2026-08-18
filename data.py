"""
data.py — Chargement des prix.

Deux sources :
  1. "yahoo"      : données RÉELLES via yfinance (à installer : pip install yfinance).
                    Mises en cache dans data_cache/ pour ne pas re-télécharger.
  2. "synthetic"  : données SIMULÉES (mouvement brownien géométrique), UNIQUEMENT
                    pour tester que le moteur tourne (smoke test). Elles sont
                    déterministes (seed fixe) et TOUJOURS étiquetées comme fausses.
                    Elles n'écrasent jamais un fichier de résultats réel.

Sortie commune : dict { ticker : DataFrame[Open, High, Low, Close, Volume] }
avec un DatetimeIndex trié. Close est ajusté des dividendes/splits.
"""

from __future__ import annotations

import os
import numpy as np
import pandas as pd


CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")


# ---------------------------------------------------------------------- #
#  DONNÉES RÉELLES                                                         #
# ---------------------------------------------------------------------- #
def _load_yahoo(tickers, start, end):
    try:
        import yfinance as yf
    except ImportError as e:
        raise SystemExit(
            "\n[ERREUR] yfinance n'est pas installé.\n"
            "  -> pip install yfinance   (ou : conda install -c conda-forge yfinance)\n"
            "Ou lance un smoke test sans réseau :  python run.py --source synthetic\n"
        ) from e

    os.makedirs(CACHE_DIR, exist_ok=True)
    out = {}
    to_download = []
    for t in tickers:
        cache = os.path.join(CACHE_DIR, f"{t}.csv")
        if os.path.exists(cache):
            df = pd.read_csv(cache, index_col=0, parse_dates=True)
            # Vérifie que le cache couvre la période demandée.
            if df.index.min() <= pd.Timestamp(start) and df.index.max() >= pd.Timestamp(end) - pd.Timedelta(days=7):
                out[t] = df.loc[start:end]
                continue
        to_download.append(t)

    if to_download:
        print(f"[data] Téléchargement Yahoo : {', '.join(to_download)}")
        raw = yf.download(
            to_download, start=start, end=end,
            auto_adjust=True, progress=False, group_by="ticker", threads=True,
        )
        for t in to_download:
            try:
                df = raw[t] if len(to_download) > 1 else raw
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except (KeyError, TypeError):
                print(f"[data] !! Pas de données pour {t}, ignoré.")
                continue
            if df.empty:
                print(f"[data] !! {t} vide, ignoré.")
                continue
            df.to_csv(os.path.join(CACHE_DIR, f"{t}.csv"))
            out[t] = df

    return out


# ---------------------------------------------------------------------- #
#  DONNÉES SYNTHÉTIQUES  (smoke test uniquement)                          #
# ---------------------------------------------------------------------- #
def _load_synthetic(tickers, start, end, seed=42):
    print("\n" + "=" * 70)
    print("  ⚠  DONNÉES SYNTHÉTIQUES (SIMULÉES) — SMOKE TEST DU MOTEUR")
    print("     Ces résultats N'ONT AUCUNE valeur prédictive. Ils servent")
    print("     seulement à vérifier que le backtest tourne sans erreur.")
    print("=" * 70 + "\n")

    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, end=end)
    n = len(dates)
    out = {}
    for i, t in enumerate(tickers):
        # Drift + vol légèrement différents par titre, avec un peu de tendance
        # pour que la stratégie de breakout ait quelque chose à mordre.
        mu = rng.normal(0.06, 0.05) / 252          # drift annualisé ~6 %
        vol = rng.uniform(0.15, 0.45) / np.sqrt(252)
        shocks = rng.normal(mu, vol, n)
        close = 100 * np.exp(np.cumsum(shocks))
        # OHLC cohérent autour du close.
        intraday = np.abs(rng.normal(0, vol, n)) * close
        open_ = close * (1 + rng.normal(0, vol / 2, n))
        high = np.maximum(open_, close) + intraday
        low = np.minimum(open_, close) - intraday
        vol_shares = rng.integers(1_000_000, 5_000_000, n)
        out[t] = pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol_shares},
            index=dates,
        )
    return out


# ---------------------------------------------------------------------- #
#  API PUBLIQUE                                                           #
# ---------------------------------------------------------------------- #
def load_prices(tickers, start, end, source="yahoo"):
    if source == "synthetic":
        return _load_synthetic(tickers, start, end)
    if source == "yahoo":
        return _load_yahoo(tickers, start, end)
    raise ValueError(f"Source inconnue : {source!r} (attendu 'yahoo' ou 'synthetic')")
