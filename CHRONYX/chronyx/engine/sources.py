"""Sources de données : MetaTrader 5 (réel/démo) ou simulation hors-ligne."""
from __future__ import annotations

import zlib

import pandas as pd

from ..config import Config
from ..data.mt5_client import MT5Client
from ..data.sample_data import generate_ohlc
from ..data.symbol_spec import SymbolSpec, indicative_spec


class SimulatedSource:
    """Données SIMULÉES : pour tester l'installation sans MetaTrader 5."""
    live = False
    name = "SIMULATION (données fictives)"

    def __init__(self, cfg: Config, bars: int = 3000) -> None:
        self.cfg = cfg
        self.bars = bars
        self._cache: dict = {}

    def spec(self, symbol: str) -> SymbolSpec:
        return indicative_spec(symbol)

    def spread_points(self, symbol: str) -> float:
        return {"XAUUSD": 25.0, "EURUSD": 8.0, "USDJPY": 10.0, "GBPUSD": 12.0}.get(symbol, 15.0)

    def rates(self, symbol: str, timeframe: str, count: int | None = None) -> pd.DataFrame:
        key = (symbol, timeframe)
        if key not in self._cache:
            from ..data.symbol_spec import TIMEFRAME_MINUTES
            base_tf = self.cfg.get("timeframes", "principal", default="M5")
            ratio = max(1, TIMEFRAME_MINUTES[timeframe] // TIMEFRAME_MINUTES[base_tf])
            seed = zlib.crc32(symbol.encode()) % 10_000  # même graine pour tous les TF d'un symbole
            if ratio == 1:
                df = generate_ohlc(symbol, timeframe, count or self.bars, seed=seed,
                                   spread_points=int(self.spread_points(symbol)))
            else:
                from ..data.sample_data import resample
                base = self.rates(symbol, base_tf)
                df = resample(base, timeframe)
            self._cache[key] = df
        return self._cache[key]

    def account(self) -> dict:
        cap = float(self.cfg.get("capital", "capital_initial"))
        return {"balance": cap, "equity": cap, "margin_free": cap, "login": "SIMULATION", "server": "—",
                "currency": "EUR", "leverage": 30}

    def is_demo(self) -> bool | None:
        return None


class MT5Source:
    live = True

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = MT5Client(cfg.get("broker", "suffixe_symboles", default="") or "")
        self.client.connect()
        acc = self.client.account()
        self.name = f"MetaTrader 5 - {acc.get('server')} ({'DÉMO' if self.client.is_demo() else 'RÉEL'})"
        if acc.get("currency") != cfg.get("general", "devise_compte", default="EUR"):
            # Pas bloquant : MT5 fournit la valeur du tick dans la devise du compte.
            self.currency_warning = f"Compte en {acc.get('currency')} (l'affichage reste dans cette devise)."
        else:
            self.currency_warning = ""

    def spec(self, symbol: str) -> SymbolSpec:
        return self.client.symbol_spec(symbol)

    def spread_points(self, symbol: str) -> float:
        return self.client.spread_points(symbol, self.spec(symbol))

    def rates(self, symbol: str, timeframe: str, count: int | None = None) -> pd.DataFrame:
        df = self.client.rates(symbol, timeframe, count or 3000)
        # La dernière bougie MT5 est EN COURS de formation : on ne l'utilise pas (pas de signal sur bougie non clôturée).
        return df.iloc[:-1].reset_index(drop=True)

    def account(self) -> dict:
        return self.client.account()

    def is_demo(self) -> bool | None:
        return self.client.is_demo()


def make_source(cfg: Config, prefer_mt5: bool = True):
    """Essaie MT5, sinon bascule en simulation (et le signale clairement)."""
    if prefer_mt5:
        try:
            return MT5Source(cfg), ""
        except Exception as e:  # MT5 absent / non connecté
            return SimulatedSource(cfg), f"MetaTrader 5 indisponible ({e}). Mode SIMULATION : données fictives."
    return SimulatedSource(cfg), "Mode SIMULATION demandé : données fictives."
