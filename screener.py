"""
screener.py — La routine du soir, automatisée.

L'idée directrice, et c'est elle qui rend l'outil défendable : **le screener
n'a pas ses propres règles**. Il importe `compute_signals` de `strategy.py`,
exactement la fonction que le backtest utilise, et `CONFIG` avec exactement les
mêmes paramètres. Conséquence : ce que ce screener sort ce soir est très
précisément ce que le backtest a mesuré sur quinze ans.

C'est le contraire de la pratique habituelle, où le screener vit dans la
plateforme de graphiques et le backtest dans un tableur : les deux dérivent, on
finit par trader autre chose que ce qu'on a validé, et on ne s'en aperçoit
jamais.

Deux écrans :

  1. SIGNAUX     — ce qui casse aujourd'hui. Rare par construction : sur un
                   univers de vingt titres, la plupart des soirs sont vides.
                   Un screener qui sort dix signaux par jour a des règles trop
                   lâches.

  2. WATCHLIST   — ce qui approche de la cassure, classé par distance. C'est
                   l'écran qu'on regarde vraiment tous les soirs : il dit quoi
                   surveiller demain, pas quoi acheter ce soir.

Chaque ligne porte son niveau d'entrée, son stop, et la taille de position que
le money management en R impose. Aucune décision n'est laissée à l'appréciation
du moment — c'est le but.

Usage :
    python screener.py
    python screener.py --universe nasdaq --capital 50000
    python screener.py --near 5          # watchlist : seuil de proximité en %
    python screener.py --source synthetic  # smoke test, sans réseau

Outil de sélection, pas une recommandation. Aucun conseil en investissement.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import pandas as pd

from config import CONFIG
from data import load_prices
from strategy import compute_signals

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")


# ===========================================================================
#  UNIVERS
# ===========================================================================
# Reprend le découpage par marché des screeners de la formation (SRD France,
# DAX, Nasdaq…). Ce sont des échantillons de départ : remplace-les par les
# listes complètes de chaque place.

UNIVERSES = {
    "default": CONFIG.universe,

    "nasdaq": [
        "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AVGO",
        "COST", "ADBE", "AMD", "NFLX", "INTC", "QCOM", "CSCO", "TXN",
    ],

    "srd_france": [
        "MC.PA", "OR.PA", "TTE.PA", "SAN.PA", "AIR.PA", "BNP.PA", "SU.PA",
        "AI.PA", "EL.PA", "DG.PA", "KER.PA", "RMS.PA", "CAP.PA", "ACA.PA",
        "GLE.PA", "ATO.PA", "ABVX.PA", "VU.PA", "ALXIL.PA", "HCO.PA",
    ],

    "dax": [
        "SAP.DE", "SIE.DE", "ALV.DE", "MBG.DE", "BMW.DE", "BAS.DE", "BAYN.DE",
        "DTE.DE", "MUV2.DE", "IFX.DE", "ADS.DE", "VOW3.DE", "RWE.DE", "DBK.DE",
    ],
}


# ===========================================================================
#  ANALYSE D'UN TITRE
# ===========================================================================

def analyse(ticker: str, df: pd.DataFrame, cfg, capital: float) -> dict | None:
    """Applique les règles du backtest au dernier jour disponible."""
    if len(df) < max(cfg.trend_ma, cfg.breakout_lookback) + 5:
        return None

    sig = compute_signals(df, cfg)
    last = sig.iloc[-1]

    px = float(last["Close"])
    stop_dist = float(last["stop_dist"])
    if pd.isna(stop_dist) or stop_dist <= 0 or pd.isna(px):
        return None

    dch_hi, dch_lo = float(last["dch_hi"]), float(last["dch_lo"])
    ma = float(last["trend_ma"])

    # Distance qu'il reste à parcourir pour déclencher la règle. Négatif = déjà
    # au-delà du niveau.
    to_break_up = (dch_hi - px) / px * 100
    to_break_dn = (px - dch_lo) / px * 100

    # --- Money management en R -------------------------------------------------
    # On risque `risk_per_trade` du capital. La taille de position n'est donc pas
    # un choix : elle découle de la distance au stop. Un titre volatil donne
    # mécaniquement une position plus petite, à risque identique.
    risk_eur = cfg.risk_per_trade * capital
    shares = risk_eur / stop_dist
    notional = shares * px

    # Plafond de poids : au-delà, on réduit et le risque réel devient < 1 R.
    cap_notional = cfg.max_weight * capital
    capped = notional > cap_notional
    if capped:
        shares = cap_notional / px
        notional = cap_notional

    turnover = float((sig["Close"] * sig["Volume"]).iloc[-60:].median())

    return {
        "ticker": ticker,
        "prix": px,
        "signal": int(last["signal"]),
        "tendance": "haussière" if px > ma else "baissière",
        "niveau_achat": dch_hi,
        "niveau_vad": dch_lo,
        "dist_cassure_h_%": to_break_up,
        "dist_cassure_b_%": to_break_dn,
        "atr": float(last["atr"]),
        "stop_dist": stop_dist,
        "stop_long": px - stop_dist,
        "stop_short": px + stop_dist,
        "actions": shares,
        "notionnel": notional,
        "plafonne": capped,
        "turnover_med": turnover,
    }


# ===========================================================================
#  AFFICHAGE
# ===========================================================================

def _table(rows: list[dict], cols: list[tuple[str, str, str]]) -> str:
    """cols = [(clé, en-tête, format)]"""
    head = "  ".join(f"{h:>{max(len(h), 10)}}" for _, h, _ in cols)
    lines = [head, "  ".join("-" * max(len(h), 10) for _, h, _ in cols)]
    for r in rows:
        cells = []
        for k, h, f in cols:
            v = r.get(k)
            s = "—" if v is None or (isinstance(v, float) and pd.isna(v)) else f.format(v)
            cells.append(f"{s:>{max(len(h), 10)}}")
        lines.append("  ".join(cells))
    return "\n".join(lines)


def report(rows: list[dict], cfg, capital: float, near: float) -> None:
    longs = [r for r in rows if r["signal"] == 1]
    shorts = [r for r in rows if r["signal"] == -1]

    print("\n" + "=" * 96)
    print(f"  1. SIGNAUX DU JOUR — cassure confirmée à la clôture")
    print("=" * 96)

    if longs:
        print("\n  ACHAT — cassure du plus-haut {} j, au-dessus de la MM{}\n".format(
            cfg.breakout_lookback, cfg.trend_ma))
        print(_table(longs, [
            ("ticker", "Titre", "{}"), ("prix", "Cours", "{:.2f}"),
            ("niveau_achat", "Niveau", "{:.2f}"), ("stop_long", "Stop", "{:.2f}"),
            ("stop_dist", "1R", "{:.2f}"), ("actions", "Qté", "{:.0f}"),
            ("notionnel", "Notionnel", "{:,.0f}"),
        ]))
    if shorts:
        print("\n  VAD — cassure du plus-bas {} j, sous la MM{}\n".format(
            cfg.breakout_lookback, cfg.trend_ma))
        print(_table(shorts, [
            ("ticker", "Titre", "{}"), ("prix", "Cours", "{:.2f}"),
            ("niveau_vad", "Niveau", "{:.2f}"), ("stop_short", "Stop", "{:.2f}"),
            ("stop_dist", "1R", "{:.2f}"), ("actions", "Qté", "{:.0f}"),
            ("notionnel", "Notionnel", "{:,.0f}"),
        ]))
    if not longs and not shorts:
        print("\n  Aucun signal. C'est le cas le plus fréquent, et c'est normal :")
        print("  une cassure de canal 55 jours filtrée par la tendance est un")
        print("  événement rare. Un screener qui parle tous les soirs ment.")

    # --- Watchlist -----------------------------------------------------------
    up = sorted(
        [r for r in rows if r["signal"] == 0 and 0 <= r["dist_cassure_h_%"] <= near
         and r["tendance"] == "haussière"],
        key=lambda r: r["dist_cassure_h_%"])
    dn = sorted(
        [r for r in rows if r["signal"] == 0 and 0 <= r["dist_cassure_b_%"] <= near
         and r["tendance"] == "baissière"],
        key=lambda r: r["dist_cassure_b_%"])

    print("\n\n" + "=" * 96)
    print(f"  2. WATCHLIST — à moins de {near:.0f} % du niveau de déclenchement")
    print("=" * 96)

    if up:
        print("\n  Côté achat\n")
        print(_table(up, [
            ("ticker", "Titre", "{}"), ("prix", "Cours", "{:.2f}"),
            ("niveau_achat", "À casser", "{:.2f}"), ("dist_cassure_h_%", "Distance", "{:.2f}%"),
            ("stop_dist", "1R", "{:.2f}"), ("actions", "Qté si OK", "{:.0f}"),
        ]))
    if dn:
        print("\n  Côté VAD\n")
        print(_table(dn, [
            ("ticker", "Titre", "{}"), ("prix", "Cours", "{:.2f}"),
            ("niveau_vad", "À casser", "{:.2f}"), ("dist_cassure_b_%", "Distance", "{:.2f}%"),
            ("stop_dist", "1R", "{:.2f}"), ("actions", "Qté si OK", "{:.0f}"),
        ]))
    if not up and not dn:
        print(f"\n  Rien à moins de {near:.0f} %. Élargis avec --near 10.")


# ===========================================================================
#  MAIN
# ===========================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description="Screener — mêmes règles que le backtest")
    ap.add_argument("--universe", default="default", choices=list(UNIVERSES))
    ap.add_argument("--capital", type=float, default=CONFIG.initial_capital)
    ap.add_argument("--near", type=float, default=5.0,
                    help="seuil de proximité de la watchlist, en %%")
    ap.add_argument("--source", default="yahoo", choices=["yahoo", "synthetic"])
    args = ap.parse_args()

    cfg = CONFIG
    tickers = UNIVERSES[args.universe]

    # Deux ans suffisent largement pour une MM200 et un canal 55 jours.
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=730)

    prices = load_prices(tickers, start.strftime("%Y-%m-%d"),
                         end.strftime("%Y-%m-%d"), source=args.source)

    rows = [r for t, df in prices.items()
            if (r := analyse(t, df, cfg, args.capital)) is not None]
    if not rows:
        raise SystemExit("Aucun titre exploitable (historique insuffisant).")

    asof = max(df.index[-1] for df in prices.values())
    print(f"\nScreener — univers « {args.universe} » — {len(rows)}/{len(tickers)} titres")
    print(f"Dernière clôture : {asof:%d/%m/%Y}   ·   Capital : {args.capital:,.0f}")
    print(f"Règles : canal {cfg.breakout_lookback} j · MM{cfg.trend_ma} · "
          f"stop {cfg.atr_mult}×ATR{cfg.atr_len} · risque {cfg.risk_per_trade:.1%}/trade")

    report(rows, cfg, args.capital, args.near)

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"screen_{args.universe}_{asof:%Y%m%d}.csv")
    pd.DataFrame(rows).sort_values("dist_cassure_h_%").to_csv(path, index=False)
    print(f"\n\nDétail complet → {path}")
    print("Outil de sélection, pas une recommandation. Aucun conseil en investissement.\n")


if __name__ == "__main__":
    main()
