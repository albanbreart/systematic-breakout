"""
engine.py — Moteur de backtest événementiel, au niveau PORTEFEUILLE.

Principes méthodologiques (ce sont eux qui distinguent un backtest sérieux
d'un joli graphique trompeur) :

  1. PAS DE LOOK-AHEAD. Un signal calculé à la clôture du jour t est exécuté
     à l'OUVERTURE du jour t+1. On ne peut jamais trader sur une information
     qu'on n'avait pas encore.

  2. COÛTS RÉALISTES. Commission + slippage appliqués à l'entrée et à la sortie.

  3. GAP RISK. Si le prix ouvre en gap au-delà du stop, on est rempli à
     l'OUVERTURE (pire prix), pas magiquement au niveau du stop.

  4. SIZING EN RISQUE (R). Chaque position risque une fraction fixe du capital
     courant. La taille dépend de la distance au stop, pas d'un montant fixe.

  5. CONTRAINTES DE PORTEFEUILLE. Nb max de positions, poids max par ligne,
     exposition brute max (levier). On ne peut pas prendre 200 trades d'un coup.

Comptabilité unifiée long/short :
    valeur_position = direction * actions * prix
    equity          = cash + Σ valeur_position
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from strategy import compute_signals


@dataclass
class Position:
    ticker: str
    direction: int        # +1 long, -1 short
    shares: float
    entry_date: pd.Timestamp
    entry_price: float
    stop: float
    risk_dollars: float   # risque initial en $ = actions * distance de stop (=1 R)
    entry_cost: float     # frais d'entrée (commission), pour un P&L par trade exact


def _prepare(prices: dict, cfg) -> tuple[pd.DatetimeIndex, dict]:
    """Calcule les signaux par titre et aligne tout sur un calendrier commun."""
    data = {t: compute_signals(df, cfg) for t, df in prices.items()}
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    calendar = pd.DatetimeIndex(all_dates)

    aligned = {}
    for t, df in data.items():
        r = df.reindex(calendar)
        r["has_bar"] = df["Close"].reindex(calendar).notna()
        # Signal de la barre PRÉCÉDENTE (exécution à t+1) + niveaux associés.
        r["sig_prev"] = r["signal"].shift(1)
        r["stopdist_prev"] = r["stop_dist"].shift(1)
        # Close "porté" pour la valorisation les jours sans barre (MTM only).
        r["mark_close"] = r["Close"].ffill()
        aligned[t] = r
    return calendar, aligned


def run_backtest(prices: dict, cfg):
    """
    Retourne :
      equity_curve : Series (equity quotidienne, index = dates)
      trades       : DataFrame (journal détaillé de chaque trade fermé)
    """
    calendar, data = _prepare(prices, cfg)

    cash = cfg.initial_capital
    positions: dict[str, Position] = {}
    equity_records = []
    trade_log = []

    cost_rate = (cfg.commission_bps + cfg.slippage_bps) / 1e4

    def mark_equity(date):
        val = cash
        for pos in positions.values():
            px = data[pos.ticker].at[date, "mark_close"]
            if np.isnan(px):
                px = pos.entry_price
            val += pos.direction * pos.shares * px
        return val

    for date in calendar:
        # ---------------------------------------------------------------- #
        #  1) GESTION DES SORTIES (stops) sur les positions ouvertes         #
        # ---------------------------------------------------------------- #
        for t in list(positions.keys()):
            row = data[t].loc[date]
            if not row["has_bar"]:
                continue  # le titre n'a pas coté ce jour : on ne touche à rien
            pos = positions[t]

            # -- Mise à jour du trailing stop (ne se resserre JAMAIS à l'envers) --
            if pos.direction == 1:
                trail = row["exit_lo"]
                if not np.isnan(trail):
                    pos.stop = max(pos.stop, trail)
                hit = row["Low"] <= pos.stop
                # Gap : si l'ouverture est déjà sous le stop, on sort à l'ouverture.
                fill = min(row["Open"], pos.stop) if hit else np.nan
            else:  # short
                trail = row["exit_hi"]
                if not np.isnan(trail):
                    pos.stop = min(pos.stop, trail)
                hit = row["High"] >= pos.stop
                fill = max(row["Open"], pos.stop) if hit else np.nan

            if hit:
                cost = pos.shares * fill * cost_rate
                cash += pos.direction * pos.shares * fill - cost
                pnl = pos.direction * pos.shares * (fill - pos.entry_price)
                # P&L net de TOUS les frais du round-trip (entrée + sortie).
                # La slippage d'entrée est déjà dans entry_price ; on retranche
                # ici la commission d'entrée + les frais de sortie.
                pnl_net = pnl - cost - pos.entry_cost
                trade_log.append({
                    "ticker": t,
                    "direction": "long" if pos.direction == 1 else "short",
                    "entry_date": pos.entry_date,
                    "exit_date": date,
                    "entry_price": pos.entry_price,
                    "exit_price": fill,
                    "shares": pos.shares,
                    "pnl": pnl_net,
                    "R_multiple": pnl_net / pos.risk_dollars if pos.risk_dollars else np.nan,
                    "bars_held": (date - pos.entry_date).days,
                })
                del positions[t]

        # ---------------------------------------------------------------- #
        #  2) ENTRÉES : signaux de la veille exécutés à l'OUVERTURE du jour  #
        # ---------------------------------------------------------------- #
        equity_now = mark_equity(date)

        # Candidats = titres avec un signal la veille, pas déjà en position.
        candidates = []
        for t, df in data.items():
            row = df.loc[date]
            if not row["has_bar"] or t in positions:
                continue
            sig = row["sig_prev"]
            if pd.isna(sig) or sig == 0:
                continue
            if np.isnan(row["Open"]) or np.isnan(row["stopdist_prev"]) or row["stopdist_prev"] <= 0:
                continue
            candidates.append((t, int(sig), row["Open"], row["stopdist_prev"]))

        # Tri déterministe (par ticker) pour la reproductibilité.
        candidates.sort(key=lambda x: x[0])

        for t, sig, open_px, stop_dist in candidates:
            if len(positions) >= cfg.max_positions:
                break

            # -- Sizing en R : on risque risk_per_trade * equity --
            risk_dollars = cfg.risk_per_trade * equity_now
            shares = risk_dollars / stop_dist
            notional = shares * open_px

            # -- Plafonds de portefeuille --
            max_notional = cfg.max_weight * equity_now
            if notional > max_notional:
                shares = max_notional / open_px
                notional = shares * open_px

            gross_now = sum(p.shares * data[p.ticker].at[date, "mark_close"]
                            for p in positions.values())
            if gross_now + notional > cfg.max_gross * equity_now:
                continue  # dépasserait l'exposition brute autorisée
            if shares <= 0:
                continue

            # -- Slippage à l'entrée : on est rempli un cran au-delà de l'open --
            fill = open_px * (1 + sig * cfg.slippage_bps / 1e4)
            cost = shares * fill * (cfg.commission_bps / 1e4)
            cash += -sig * shares * fill - cost  # long: -cash ; short: +cash

            stop0 = fill - sig * stop_dist
            positions[t] = Position(
                ticker=t, direction=sig, shares=shares,
                entry_date=date, entry_price=fill, stop=stop0,
                risk_dollars=shares * stop_dist, entry_cost=cost,
            )

        # ---------------------------------------------------------------- #
        #  3) VALORISATION DE FIN DE JOURNÉE                                 #
        # ---------------------------------------------------------------- #
        eq = mark_equity(date)
        equity_records.append((date, eq))
        if eq <= 0:
            print(f"[engine] Ruine à {date.date()} — arrêt.")
            break

    equity_curve = pd.Series(
        {d: e for d, e in equity_records}, name="equity"
    ).sort_index()
    trades = pd.DataFrame(trade_log)
    return equity_curve, trades
