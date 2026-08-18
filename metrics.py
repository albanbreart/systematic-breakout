"""
metrics.py — Métriques de performance et de risque.

Ce sont exactement les chiffres qu'un recruteur quant te demandera de savoir
calculer ET interpréter. Chaque fonction est volontairement explicite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def cagr(equity: pd.Series, ann: int) -> float:
    years = len(equity) / ann
    if years <= 0 or equity.iloc[0] <= 0:
        return np.nan
    return (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1


def ann_vol(equity: pd.Series, ann: int) -> float:
    return _returns(equity).std(ddof=0) * np.sqrt(ann)


def sharpe(equity: pd.Series, ann: int, rf: float = 0.0) -> float:
    r = _returns(equity)
    excess = r - rf / ann
    sd = r.std(ddof=0)
    return np.sqrt(ann) * excess.mean() / sd if sd > 0 else np.nan


def sortino(equity: pd.Series, ann: int, rf: float = 0.0) -> float:
    r = _returns(equity)
    excess = r - rf / ann
    downside = r[r < 0].std(ddof=0)
    return np.sqrt(ann) * excess.mean() / downside if downside > 0 else np.nan


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1
    return dd.min()


def calmar(equity: pd.Series, ann: int) -> float:
    mdd = abs(max_drawdown(equity))
    return cagr(equity, ann) / mdd if mdd > 0 else np.nan


def trade_stats(trades: pd.DataFrame) -> dict:
    if trades is None or trades.empty:
        return {"n_trades": 0}
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    gross_win = wins["pnl"].sum()
    gross_loss = abs(losses["pnl"].sum())
    return {
        "n_trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "avg_R": trades["R_multiple"].mean(),
        "expectancy_R": trades["R_multiple"].mean(),   # espérance par trade, en R
        "avg_win_R": wins["R_multiple"].mean() if len(wins) else np.nan,
        "avg_loss_R": losses["R_multiple"].mean() if len(losses) else np.nan,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else np.nan,
        "avg_days_held": trades["bars_held"].mean(),
        "pct_long": (trades["direction"] == "long").mean(),
    }


def summary(equity: pd.Series, trades: pd.DataFrame, cfg,
            benchmark: pd.Series | None = None) -> dict:
    ann, rf = cfg.ann_factor, cfg.risk_free
    s = {
        "total_return": equity.iloc[-1] / equity.iloc[0] - 1,
        "CAGR": cagr(equity, ann),
        "ann_vol": ann_vol(equity, ann),
        "sharpe": sharpe(equity, ann, rf),
        "sortino": sortino(equity, ann, rf),
        "max_drawdown": max_drawdown(equity),
        "calmar": calmar(equity, ann),
    }
    s.update(trade_stats(trades))
    if benchmark is not None and len(benchmark) > 1:
        b = benchmark.reindex(equity.index).ffill().dropna()
        s["benchmark_CAGR"] = cagr(b, ann)
        s["benchmark_sharpe"] = sharpe(b, ann, rf)
        s["benchmark_max_dd"] = max_drawdown(b)
    return s
