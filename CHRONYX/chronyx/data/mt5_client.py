"""Connexion à MetaTrader 5.

Méthode recommandée (la plus sûre) : ouvrir MetaTrader 5, se connecter au
compte (démo de préférence) dans le terminal, puis lancer CHRONYX.
Le robot se raccroche alors à la session ouverte SANS jamais manipuler votre
mot de passe.

Option avancée : identifiants stockés dans le Gestionnaire d'identifiants
Windows (module `keyring`), jamais en clair. Voir chronyx/secrets.py.

Le paquet MetaTrader5 n'existe que sous Windows. Sur un autre système, ce
module reste importable mais `available()` renvoie False.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .symbol_spec import SymbolSpec

log = logging.getLogger(__name__)

try:  # pragma: no cover - dépend de Windows
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # ImportError ou autre
    mt5 = None


class MT5Error(RuntimeError):
    pass


def available() -> bool:
    return mt5 is not None


_TF_ATTR = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "M30": "TIMEFRAME_M30",
            "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}


class MT5Client:
    def __init__(self, symbol_suffix: str = "") -> None:
        self.suffix = symbol_suffix
        self.connected = False
        self._utc_offset_s: int | None = None

    # ------------------------------------------------------------------ fuseau du serveur
    def server_utc_offset_seconds(self, probe_symbol: str = "EURUSD") -> int:
        """MT5 horodate en HEURE DU SERVEUR (souvent UTC+2/+3), pas en UTC.

        Le décalage est déduit d'une cotation récente (marché ouvert). À défaut
        (week-end), on utilise MT5_UTC_OFFSET_HEURES du fichier .env, sinon 0 avec avertissement.
        """
        if self._utc_offset_s is not None:
            return self._utc_offset_s
        t = mt5.symbol_info_tick(self.broker_symbol(probe_symbol)) if mt5 else None
        if t is not None:
            diff = t.time - time.time()
            hours = round(diff / 3600)
            if abs(hours) <= 14 and abs(diff - hours * 3600) < 300:
                self._utc_offset_s = int(hours * 3600)
                log.info("Décalage horaire du serveur MT5 : UTC%+d", hours)
                return self._utc_offset_s
        env = os.getenv("MT5_UTC_OFFSET_HEURES")
        if env:
            self._utc_offset_s = int(float(env) * 3600)
            return self._utc_offset_s
        log.warning("Décalage horaire du serveur MT5 inconnu (marché fermé ?) : UTC supposé.")
        return 0

    # ------------------------------------------------------------------ connexion
    def connect(self) -> None:
        if mt5 is None:
            raise MT5Error("Le module MetaTrader5 n'est pas installé (Windows uniquement).")
        kwargs: dict[str, Any] = {}
        path = os.getenv("MT5_TERMINAL_PATH")
        if path:
            kwargs["path"] = path
        login = os.getenv("MT5_LOGIN")
        server = os.getenv("MT5_SERVER")
        if login and server:
            from ..secrets import get_mt5_password  # import local : keyring facultatif
            pwd = get_mt5_password(login)
            if pwd:
                kwargs.update(login=int(login), server=server, password=pwd)
        if not mt5.initialize(**kwargs):
            err = mt5.last_error()
            raise MT5Error(f"Échec de connexion à MetaTrader 5 : {err}. Le terminal est-il ouvert et connecté ?")
        self.connected = True
        acc = mt5.account_info()
        if acc is None:
            raise MT5Error("Terminal ouvert mais aucun compte connecté.")
        log.info("Connecté à MT5 : serveur=%s, compte=%s, démo=%s", acc.server, acc.login, self.is_demo())

    def shutdown(self) -> None:
        if mt5 is not None and self.connected:
            mt5.shutdown()
        self.connected = False

    def _require(self) -> None:
        if not self.connected:
            raise MT5Error("Non connecté à MetaTrader 5.")

    def is_alive(self) -> bool:
        """Détection de perte de connexion au serveur du broker."""
        if mt5 is None or not self.connected:
            return False
        info = mt5.terminal_info()
        return bool(info and info.connected)

    # ------------------------------------------------------------------ compte
    def account(self) -> dict[str, Any]:
        self._require()
        acc = mt5.account_info()
        if acc is None:
            raise MT5Error("Impossible de lire les informations du compte.")
        return acc._asdict()

    def is_demo(self) -> bool:
        self._require()
        acc = mt5.account_info()
        return acc is not None and acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO

    # ------------------------------------------------------------------ symboles
    def broker_symbol(self, symbol: str) -> str:
        return f"{symbol}{self.suffix}"

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        self._require()
        name = self.broker_symbol(symbol)
        if not mt5.symbol_select(name, True):
            raise MT5Error(f"Symbole {name} introuvable chez ce broker.")
        si = mt5.symbol_info(name)
        if si is None:
            raise MT5Error(f"Spécifications indisponibles pour {name}.")
        return SymbolSpec(
            name=symbol, digits=si.digits, point=si.point, contract_size=si.trade_contract_size,
            volume_min=si.volume_min, volume_step=si.volume_step, volume_max=si.volume_max,
            tick_size=si.trade_tick_size, tick_value=si.trade_tick_value,
            base_currency=si.currency_base, profit_currency=si.currency_profit,
            stops_level_points=si.trade_stops_level, source="mt5",
        )

    def tick(self, symbol: str) -> dict[str, Any]:
        self._require()
        t = mt5.symbol_info_tick(self.broker_symbol(symbol))
        if t is None:
            raise MT5Error(f"Pas de cotation pour {symbol}.")
        d = t._asdict()
        d["time"] = datetime.fromtimestamp(t.time - self.server_utc_offset_seconds(symbol), tz=timezone.utc)
        return d

    def spread_points(self, symbol: str, spec: SymbolSpec) -> float:
        t = self.tick(symbol)
        return round((t["ask"] - t["bid"]) / spec.point, 1)

    def rates(self, symbol: str, timeframe: str, count: int = 1000) -> pd.DataFrame:
        """Bougies (prix BID chez MT5). Colonnes : time(UTC), open, high, low, close, tick_volume, spread."""
        self._require()
        tf = getattr(mt5, _TF_ATTR[timeframe])
        arr = mt5.copy_rates_from_pos(self.broker_symbol(symbol), tf, 0, count)
        if arr is None or len(arr) == 0:
            raise MT5Error(f"Aucune donnée pour {symbol} {timeframe} : {mt5.last_error()}")
        df = pd.DataFrame(arr)
        df["time"] = pd.to_datetime(df["time"] - self.server_utc_offset_seconds(symbol), unit="s", utc=True)
        return df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]

    def margin_for(self, symbol: str, lots: float, buy: bool) -> float | None:
        self._require()
        t = self.tick(symbol)
        otype = mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL
        price = t["ask"] if buy else t["bid"]
        return mt5.order_calc_margin(otype, self.broker_symbol(symbol), lots, price)

    def positions(self) -> list[dict[str, Any]]:
        self._require()
        pos = mt5.positions_get()
        return [p._asdict() for p in pos] if pos else []
