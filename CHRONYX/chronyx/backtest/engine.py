"""Moteur de backtesting bougie par bougie.

Hypothèses (prudentes) :
 - Les bougies sont des prix BID (comme MT5). Achat au ASK = BID + spread.
 - Le signal est calculé sur la bougie i CLÔTURÉE ; l'entrée se fait à
   l'OUVERTURE de la bougie i+1 (pas de look-ahead).
 - Slippage défavorable appliqué à l'entrée et aux sorties sur stop.
 - Si SL et TP sont touchés dans la même bougie, on suppose que le SL a été
   touché en premier (hypothèse pessimiste).
 - Gap au-delà du stop : sortie au prix d'ouverture (pire que le stop).
 - Commission aller-retour et swap par nuit déduits.
 - La taille de position est recalculée à chaque trade via plan_trade :
   un trade refusé par la gestion du risque n'est PAS pris.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..data.symbol_spec import SymbolSpec
from ..risk.position_sizing import plan_trade
from .metrics import compute_metrics


@dataclass
class BacktestConfig:
    initial_balance: float = 300.0
    risk_pct: float = 0.5
    rr: float = 1.5
    spread_points: float | None = None   # None => colonne 'spread' des données
    commission_per_lot_rt: float = 0.0
    slippage_points: float = 2.0
    swap_per_lot_night: float = 0.0      # en € par lot et par nuit (négatif = coût)
    leverage: float | None = None        # None => levier ESMA particuliers de l'instrument
    max_margin_pct: float = 50.0
    max_spread_pct_of_stop: float = 15.0
    break_even_r: float = 0.0            # 0 = désactivé
    max_bars_in_trade: int = 0           # 0 = illimité ; sinon sortie forcée au close


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    metrics: dict
    refused: int
    refusal_reasons: dict = field(default_factory=dict)
    simulated_data: bool = False


def run_backtest(prepared: pd.DataFrame, spec: SymbolSpec, cfg: BacktestConfig,
                 blocked: pd.Series | None = None, strategy_name: str = "") -> BacktestResult:
    d = prepared.reset_index(drop=True)
    n = len(d)
    o, h, l, c = (d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    times = d["time"]
    spread_col = (np.full(n, cfg.spread_points, dtype=float) if cfg.spread_points is not None
                  else d["spread"].to_numpy(dtype=float))
    longs = d["long_signal"].fillna(False).to_numpy(dtype=bool)
    shorts = d["short_signal"].fillna(False).to_numpy(dtype=bool)
    sl_dist = d["sl_distance"].to_numpy(dtype=float)
    blk = blocked.reindex(d.index).fillna(False).to_numpy(dtype=bool) if blocked is not None else np.zeros(n, bool)

    slip = cfg.slippage_points * spec.point
    balance = cfg.initial_balance
    trades: list[dict] = []
    equity_points = [{"time": times.iloc[0], "equity": balance}]
    refused = 0
    reasons_count: dict[str, int] = {}

    pos = None  # dict de la position ouverte
    for i in range(n - 1):
        # ---------------- gestion de la position ouverte sur la bougie i
        if pos is not None and i >= pos["entry_bar"]:
            sp = spread_col[i] * spec.point
            exit_price = None
            reason = ""
            if pos["dir"] == 1:  # achat : on sort au BID
                if o[i] <= pos["sl"] and i > pos["entry_bar"]:
                    exit_price, reason = o[i] - slip, "gap SL"
                elif l[i] <= pos["sl"]:
                    exit_price, reason = pos["sl"] - slip, "SL"
                elif h[i] >= pos["tp"]:
                    exit_price, reason = pos["tp"], "TP"
            else:  # vente : on sort au ASK = bid + spread
                if o[i] + sp >= pos["sl"] and i > pos["entry_bar"]:
                    exit_price, reason = o[i] + sp + slip, "gap SL"
                elif h[i] + sp >= pos["sl"]:
                    exit_price, reason = pos["sl"] + slip, "SL"
                elif l[i] + sp <= pos["tp"]:
                    exit_price, reason = pos["tp"], "TP"
            if exit_price is None and cfg.max_bars_in_trade and i - pos["entry_bar"] + 1 >= cfg.max_bars_in_trade:
                exit_price = c[i] if pos["dir"] == 1 else c[i] + sp
                reason = "temps"
            if exit_price is not None:
                balance = _close(pos, exit_price, reason, times.iloc[i], spec, cfg, balance, trades)
                equity_points.append({"time": times.iloc[i], "equity": balance})
                pos = None
            elif cfg.break_even_r > 0 and not pos["be"]:
                fav = (h[i] - pos["entry"]) if pos["dir"] == 1 else (pos["entry"] - (l[i] + sp))
                if fav >= cfg.break_even_r * pos["risk_dist"]:
                    pos["sl"], pos["be"] = pos["entry"], True

        # ---------------- nouveau signal sur la bougie i (clôturée) -> entrée à l'ouverture de i+1
        if pos is None and not blk[i] and (longs[i] or shorts[i]) and np.isfinite(sl_dist[i]):
            direction = 1 if longs[i] else -1
            sp_next = spread_col[i + 1] * spec.point
            entry = o[i + 1] + sp_next + slip if direction == 1 else o[i + 1] - slip
            plan = plan_trade(spec, "BUY" if direction == 1 else "SELL", balance, cfg.risk_pct, entry,
                              sl_dist[i], cfg.rr, spread_col[i + 1], cfg.commission_per_lot_rt, cfg.leverage,
                              cfg.max_spread_pct_of_stop, cfg.max_margin_pct)
            if not plan.accepted:
                refused += 1
                key = plan.reason_codes[0] if plan.reason_codes else "autre"
                reasons_count[key] = reasons_count.get(key, 0) + 1
                continue
            pos = {"dir": direction, "entry": entry, "sl": plan.stop_loss, "tp": plan.take_profit, "lots": plan.lots,
                   "entry_bar": i + 1, "entry_time": times.iloc[i + 1], "risk_eur": plan.risk_eur,
                   "risk_dist": sl_dist[i], "be": False, "strategy": strategy_name}

    if pos is not None:  # clôture de fin de test
        last = n - 1
        exit_price = c[last] if pos["dir"] == 1 else c[last] + spread_col[last] * spec.point
        balance = _close(pos, exit_price, "fin du test", times.iloc[last], spec, cfg, balance, trades)
        equity_points.append({"time": times.iloc[last], "equity": balance})

    tdf = pd.DataFrame(trades)
    edf = pd.DataFrame(equity_points)
    metrics = compute_metrics(tdf, edf, cfg.initial_balance)
    return BacktestResult(tdf, edf, metrics, refused, reasons_count, bool(prepared.attrs.get("simulated")))


def _close(pos: dict, exit_price: float, reason: str, t, spec: SymbolSpec, cfg: BacktestConfig,
           balance: float, trades: list[dict]) -> float:
    gross = (exit_price - pos["entry"]) * pos["dir"] * spec.value_per_price_unit(pos["lots"])
    commission = cfg.commission_per_lot_rt * pos["lots"]
    nights = max(0, (pd.Timestamp(t).normalize() - pd.Timestamp(pos["entry_time"]).normalize()).days)
    swap = cfg.swap_per_lot_night * pos["lots"] * nights
    pnl = gross - commission + swap
    trades.append({"symbol": spec.name, "strategy": pos["strategy"], "direction": "BUY" if pos["dir"] == 1 else "SELL",
                   "entry_time": pos["entry_time"], "exit_time": t, "entry": pos["entry"], "exit": exit_price,
                   "sl": pos["sl"], "tp": pos["tp"], "lots": pos["lots"], "risk_eur": pos["risk_eur"],
                   "gross": gross, "commission": commission, "swap": swap, "pnl": pnl,
                   "r_multiple": pnl / pos["risk_eur"] if pos["risk_eur"] else 0.0,
                   "exit_reason": reason, "balance_after": balance + pnl})
    return balance + pnl


def run_periods(prepared: pd.DataFrame, spec: SymbolSpec, cfg: BacktestConfig, n_periods: int = 4,
                blocked: pd.Series | None = None, strategy_name: str = "") -> list[BacktestResult]:
    """Découpe l'historique en périodes chronologiques indépendantes pour juger la régularité."""
    size = len(prepared) // n_periods
    out = []
    for k in range(n_periods):
        seg = prepared.iloc[k * size:(k + 1) * size]
        seg.attrs.update(prepared.attrs)
        b = blocked.iloc[k * size:(k + 1) * size].reset_index(drop=True) if blocked is not None else None
        out.append(run_backtest(seg, spec, cfg, b, strategy_name))
    return out
