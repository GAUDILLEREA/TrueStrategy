"""Pipeline d'analyse d'un instrument : données -> contrôles -> signal -> risque -> décision.

Utilisé à la fois par le moteur autonome (bot.py) et par le dashboard, afin que
les décisions affichées soient EXACTEMENT celles du robot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from ..analysis.indicators import swing_levels
from ..analysis.regime import Regime, classify
from ..config import Config
from ..data.quality import QualityReport, check_ohlc
from ..data.symbol_spec import SymbolSpec
from ..news.calendar import CalendarStatus, news_block, next_event
from ..risk.guards import AccountState, RiskGuard
from ..risk.position_sizing import TradePlan, plan_trade
from ..strategies.base import Signal
from ..strategies.registry import build


@dataclass
class Analysis:
    symbol: str
    timeframe: str
    spec: SymbolSpec
    data: pd.DataFrame
    quality: QualityReport
    regime: Regime
    signal: Signal
    levels: dict
    spread_points: float
    plan: TradePlan | None
    blocks: list[str] = field(default_factory=list)
    next_event: dict | None = None
    bar_time: pd.Timestamp | None = None

    @property
    def tradable(self) -> bool:
        return self.signal.direction is not None and self.plan is not None and self.plan.accepted and not self.blocks

    @property
    def decision(self) -> str:
        if self.tradable:
            return f"TRADE POSSIBLE : {'ACHAT' if self.signal.direction == 'BUY' else 'VENTE'}"
        return "PAS DE TRADE"

    def no_trade_reasons(self) -> list[str]:
        out = list(self.blocks)
        if self.signal.direction is None:
            out += [f"Condition non remplie : {m}" for m in self.signal.missing]
        elif self.plan is not None and not self.plan.accepted:
            out += self.plan.reasons
        return out


def default_account_state(account: dict) -> AccountState:
    bal, eq = float(account["balance"]), float(account["equity"])
    return AccountState(balance=bal, equity=eq, start_of_day_balance=bal, start_of_week_balance=bal, peak_equity=max(bal, eq))


def analyze(cfg: Config, source, symbol: str, calendar: CalendarStatus, state: AccountState,
            now: datetime | None = None, strategy_name: str = "trend_scalping") -> Analysis:
    now = now or datetime.now(timezone.utc)
    r = cfg.risk
    tf = cfg.get("timeframes", "principal", default="M5")
    sparams = cfg.get("strategies", strategy_name, default={}) or {}
    strat = build(strategy_name, sparams, r["stop_loss_atr_mult"], tf)
    htf_tf = sparams.get("timeframe_confirmation", "H1")

    spec = source.spec(symbol)
    df = source.rates(symbol, tf)
    htf = source.rates(symbol, htf_tf)
    quality = check_ohlc(df, tf, check_freshness=source.live, now=now)
    prepared = strat.prepare(df, htf)
    signal = strat.explain_last(prepared, symbol, float(r["risk_reward"]))
    regime = classify(prepared)
    levels = swing_levels(prepared.tail(300))
    spread = float(source.spread_points(symbol))

    guard = RiskGuard(r, cfg.get("horaires"), cfg.get("general", "fuseau_horaire", default="Europe/Paris"))
    blocks: list[str] = []
    blocks += [f"Données : {i}" for i in quality.issues]
    if not regime.favorable_scalping:
        blocks.append(f"Régime défavorable : {regime.comment}")
    cal = cfg.get("calendrier", default={}) or {}
    blocks += news_block(calendar, symbol, now, int(cal.get("minutes_avant", 15)), int(cal.get("minutes_apres", 15)),
                         tuple(cal.get("impacts_bloquants", ["high"])))
    blocks += guard.schedule_check(now)
    blocks += guard.spread_check(symbol, spread, cfg.spread_max_points(symbol))
    blocks += guard.account_checks(state, now)
    blocks += guard.duplicate_check(symbol, state)

    plan = None
    if signal.direction:
        entry = signal.entry + (spread * spec.point if signal.direction == "BUY" else 0.0)
        plan = plan_trade(spec, signal.direction, state.balance, float(r["risque_par_trade_pct"]), entry,
                          signal.sl_distance, float(r["risk_reward"]), spread,
                          float(cfg.get("broker", "commission_par_lot_aller_retour", default=0.0)),
                          max_spread_pct_of_stop=float(r.get("spread_max_pct_du_stop", 15)),
                          max_margin_pct=float(r.get("marge_max_pct_capital", 50)))

    return Analysis(symbol=symbol, timeframe=tf, spec=spec, data=prepared, quality=quality, regime=regime,
                    signal=signal, levels=levels, spread_points=spread, plan=plan, blocks=blocks,
                    next_event=next_event(calendar, symbol, now), bar_time=prepared["time"].iloc[-1])
