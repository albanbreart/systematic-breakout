"""
run.py — Point d'entrée. Orchestration + rapport + sauvegarde.

Exemples :
  python run.py --source synthetic          # smoke test (aucun réseau requis)
  python run.py --source yahoo              # backtest réel (pip install yfinance)
  python run.py --source yahoo --plot       # + graphique equity curve
  python run.py --source yahoo --start 2015-01-01 --end 2024-12-31

Les résultats sont écrits dans outputs/, préfixés par la source, pour que le
smoke test synthétique n'écrase JAMAIS un résultat réel.
"""

from __future__ import annotations

import argparse
import os

import pandas as pd

from config import CONFIG
from data import load_prices
from engine import run_backtest
from metrics import summary, max_drawdown

OUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.4f}"
    return str(v)


def _print_block(title, d, pct_keys=()):
    print(f"\n── {title} " + "─" * max(2, 50 - len(title)))
    for k, v in d.items():
        if isinstance(v, float) and k in pct_keys:
            print(f"  {k:<22} {v * 100:>10.2f} %")
        elif isinstance(v, float):
            print(f"  {k:<22} {v:>12.3f}")
        else:
            print(f"  {k:<22} {v:>12}")


def build_benchmark(cfg, source):
    """Buy & hold du benchmark, ramené en base 'capital initial'."""
    try:
        bpx = load_prices([cfg.benchmark], cfg.start, cfg.end, source=source)
    except SystemExit:
        raise
    except Exception:
        return None
    if cfg.benchmark not in bpx:
        return None
    close = bpx[cfg.benchmark]["Close"]
    return cfg.initial_capital * close / close.iloc[0]


def main():
    ap = argparse.ArgumentParser(description="Backtest breakout / suivi de tendance.")
    ap.add_argument("--source", choices=["yahoo", "synthetic"], default="yahoo")
    ap.add_argument("--start", default=CONFIG.start)
    ap.add_argument("--end", default=CONFIG.end)
    ap.add_argument("--plot", action="store_true", help="Trace l'equity curve (matplotlib)")
    args = ap.parse_args()

    cfg = CONFIG
    cfg.start, cfg.end = args.start, args.end

    pct = ("total_return", "CAGR", "ann_vol", "max_drawdown", "win_rate",
           "benchmark_CAGR", "benchmark_max_dd", "pct_long")

    # 1) Données
    prices = load_prices(cfg.universe, cfg.start, cfg.end, source=args.source)
    if not prices:
        raise SystemExit("Aucune donnée chargée — vérifie l'univers / la connexion.")
    print(f"[run] {len(prices)} titres chargés ({args.source}).")

    # 2) Backtest
    equity, trades = run_backtest(prices, cfg)
    benchmark = build_benchmark(cfg, args.source)

    # 3) Rapport — période complète
    print("\n" + "#" * 60)
    print(f"#  RÉSULTATS — source={args.source}  période={cfg.start}→{cfg.end}")
    print("#" * 60)
    full = summary(equity, trades, cfg, benchmark)
    _print_block("Performance & risque (période complète)", full, pct)

    # 4) Découpe In-Sample / Out-of-Sample
    #    On juge la robustesse sur la partie qu'on n'a PAS servie à régler.
    oos = pd.Timestamp(cfg.oos_start)
    eq_is, eq_oos = equity.loc[:oos], equity.loc[oos:]
    if len(eq_is) > 10 and len(eq_oos) > 10:
        tr_is = trades[trades["exit_date"] < oos] if not trades.empty else trades
        tr_oos = trades[trades["exit_date"] >= oos] if not trades.empty else trades
        _print_block(f"IN-SAMPLE  (< {cfg.oos_start})", summary(eq_is, tr_is, cfg), pct)
        _print_block(f"OUT-OF-SAMPLE (≥ {cfg.oos_start})", summary(eq_oos, tr_oos, cfg), pct)
        print("\n  → Si l'OOS s'effondre vs l'IS, la stratégie est probablement sur-ajustée.")

    # 5) Sauvegarde (préfixée par la source : pas d'écrasement réel/synthétique)
    os.makedirs(OUT_DIR, exist_ok=True)
    pref = args.source
    equity.to_csv(os.path.join(OUT_DIR, f"{pref}_equity.csv"))
    if not trades.empty:
        trades.to_csv(os.path.join(OUT_DIR, f"{pref}_trades.csv"), index=False)
    print(f"\n[run] Résultats écrits dans outputs/{pref}_equity.csv "
          f"({len(trades)} trades → {pref}_trades.csv)")

    # 6) Graphique optionnel
    if args.plot:
        import matplotlib.pyplot as plt
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                       gridspec_kw={"height_ratios": [3, 1]})
        ax1.plot(equity.index, equity.values, label="Stratégie", lw=1.3)
        if benchmark is not None:
            b = benchmark.reindex(equity.index).ffill()
            ax1.plot(b.index, b.values, label=f"Buy & Hold {cfg.benchmark}",
                     lw=1.0, alpha=0.7)
        ax1.set_title(f"Equity curve — {args.source} ({cfg.start}→{cfg.end})")
        ax1.legend(); ax1.grid(alpha=0.3)
        dd = equity / equity.cummax() - 1
        ax2.fill_between(dd.index, dd.values, 0, color="crimson", alpha=0.4)
        ax2.set_title("Drawdown"); ax2.grid(alpha=0.3)
        fig.tight_layout()
        png = os.path.join(OUT_DIR, f"{pref}_equity.png")
        fig.savefig(png, dpi=120)
        print(f"[run] Graphique : outputs/{pref}_equity.png")


if __name__ == "__main__":
    main()
