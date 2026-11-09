"""Protections obligatoires (coupe-circuits).

Chaque vérification renvoie une liste de raisons de blocage, en français.
Liste vide = autorisé. Ces protections fonctionnent indépendamment du
dashboard : le moteur (engine/bot.py) les applique à chaque cycle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import ROOT

KILL_SWITCH_FILE = ROOT / "data" / "STOP_GLOBAL"

_DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def kill_switch_active(path: Path | None = None) -> bool:
    return (path or KILL_SWITCH_FILE).exists()


def activate_kill_switch(reason: str, path: Path | None = None) -> None:
    path = path or KILL_SWITCH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{datetime.now().isoformat()} | {reason}\n", encoding="utf-8")


def release_kill_switch(path: Path | None = None) -> None:
    path = path or KILL_SWITCH_FILE
    if path.exists():
        path.unlink()


@dataclass
class AccountState:
    balance: float
    equity: float
    start_of_day_balance: float
    start_of_week_balance: float
    peak_equity: float
    trades_today: int = 0
    open_positions: int = 0
    last_loss_time: datetime | None = None
    open_symbols: set[str] = field(default_factory=set)


class RiskGuard:
    def __init__(self, risk_cfg: dict, hours_cfg: dict | None = None, tz: str = "Europe/Paris") -> None:
        self.r = risk_cfg
        self.h = hours_cfg or {}
        self.tz = ZoneInfo(tz)

    # ---------------------------------------------------------------- compte
    def account_checks(self, s: AccountState, now: datetime) -> list[str]:
        out: list[str] = []
        if kill_switch_active():
            out.append("STOP GLOBAL activé : aucune nouvelle position.")
        day_loss = (s.start_of_day_balance - s.equity) / s.start_of_day_balance * 100
        if day_loss >= self.r["perte_max_jour_pct"]:
            out.append(f"Perte du jour {day_loss:.2f} % >= limite {self.r['perte_max_jour_pct']} %.")
        week_loss = (s.start_of_week_balance - s.equity) / s.start_of_week_balance * 100
        if week_loss >= self.r["perte_max_semaine_pct"]:
            out.append(f"Perte de la semaine {week_loss:.2f} % >= limite {self.r['perte_max_semaine_pct']} %.")
        dd = (s.peak_equity - s.equity) / s.peak_equity * 100 if s.peak_equity > 0 else 0
        if dd >= self.r["drawdown_max_pct"]:
            out.append(f"Drawdown {dd:.2f} % >= limite {self.r['drawdown_max_pct']} %.")
        if s.trades_today >= self.r["trades_max_par_jour"]:
            out.append(f"Nombre maximum de trades du jour atteint ({self.r['trades_max_par_jour']}).")
        if s.open_positions >= self.r["positions_simultanees_max"]:
            out.append(f"Nombre maximum de positions simultanées atteint ({self.r['positions_simultanees_max']}).")
        pause = self.r.get("pause_apres_perte_min", 0)
        if pause and s.last_loss_time and now - s.last_loss_time < timedelta(minutes=pause):
            remaining = pause - (now - s.last_loss_time).total_seconds() / 60
            out.append(f"Pause après perte : encore {remaining:.0f} min.")
        return out

    def hard_stop_reached(self, s: AccountState) -> bool:
        """Drawdown max => arrêt complet du robot (STOP GLOBAL automatique)."""
        dd = (s.peak_equity - s.equity) / s.peak_equity * 100 if s.peak_equity > 0 else 0
        return dd >= self.r["drawdown_max_pct"]

    # ---------------------------------------------------------------- marché
    def spread_check(self, symbol: str, spread_points: float, max_points: float) -> list[str]:
        if spread_points > max_points:
            return [f"Spread {symbol} trop élevé : {spread_points:.0f} points (max {max_points:.0f})."]
        return []

    def duplicate_check(self, symbol: str, s: AccountState) -> list[str]:
        if symbol in s.open_symbols:
            return [f"Une position est déjà ouverte sur {symbol} (protection anti-doublon)."]
        return []

    def schedule_check(self, now: datetime) -> list[str]:
        if not self.h:
            return []
        local = now.astimezone(self.tz)
        days = self.h.get("jours") or _DAYS_FR[:5]
        if _DAYS_FR[local.weekday()] not in days:
            return [f"Jour non autorisé ({_DAYS_FR[local.weekday()]})."]
        plages = self.h.get("plages") or []
        if not plages:
            return []
        t = local.time()
        for p in plages:
            if time.fromisoformat(p["debut"]) <= t < time.fromisoformat(p["fin"]):
                return []
        txt = ", ".join(f"{p['debut']}-{p['fin']}" for p in plages)
        return [f"Hors des horaires de trading ({local:%H:%M}, plages autorisées : {txt})."]
