"""Spécifications d'un symbole (contrat) chez le broker.

En production, les spécifications DOIVENT venir de MetaTrader 5 (symbol_info),
car elles varient d'un broker à l'autre (taille de contrat, lot minimum,
valeur du tick, nombre de décimales...).

Les valeurs "indicatives" ci-dessous servent uniquement au mode hors-ligne
(tests, backtests sur données simulées). Elles sont signalées comme telles.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


@dataclass(frozen=True)
class SymbolSpec:
    name: str
    digits: int
    point: float                 # plus petite variation de prix affichée
    contract_size: float         # ex : 100 onces pour XAUUSD, 100 000 pour EURUSD
    volume_min: float            # lot minimum
    volume_step: float           # pas de lot
    volume_max: float
    tick_size: float             # variation minimale de prix
    tick_value: float            # valeur d'1 tick pour 1 lot, en DEVISE DU COMPTE
    base_currency: str
    profit_currency: str
    stops_level_points: int = 0  # distance minimale SL/TP imposée par le broker
    source: str = "indicatif"    # "mt5" ou "indicatif"

    @property
    def pip_size(self) -> float:
        """Taille d'un pip : 0.0001 (Forex), 0.01 (paires JPY), 0.1 pour l'or (convention courante)."""
        if self.base_currency == "XAU":
            return 0.1
        return 0.01 if self.profit_currency == "JPY" else 0.0001

    def value_per_price_unit(self, lots: float) -> float:
        """Gain/perte en devise du compte pour un mouvement de prix de 1.0."""
        return lots * self.tick_value / self.tick_size

    def money_for_distance(self, price_distance: float, lots: float) -> float:
        return abs(price_distance) * self.value_per_price_unit(lots)

    def pip_value(self, lots: float = 1.0) -> float:
        return self.money_for_distance(self.pip_size, lots)

    def normalize_volume(self, lots: float) -> float:
        """Arrondit VERS LE BAS au pas de lot (jamais vers le haut : cela augmenterait le risque)."""
        if lots <= 0:
            return 0.0
        steps = int(lots / self.volume_step + 1e-9)
        vol = round(steps * self.volume_step, 8)
        return min(vol, self.volume_max)

    def to_dict(self) -> dict:
        return asdict(self)


# Taux de conversion indicatifs (hors-ligne uniquement). En ligne, MT5 fournit tick_value
# directement dans la devise du compte.
DEFAULT_RATES_TO_EUR = {"EUR": 1.0, "USD": 0.92, "JPY": 0.0061, "GBP": 1.17, "CHF": 1.05, "CAD": 0.67, "AUD": 0.60}

_INDICATIVE = {
    # name: (digits, point, contract, base, profit)
    "XAUUSD": (2, 0.01, 100.0, "XAU", "USD"),
    "EURUSD": (5, 0.00001, 100_000.0, "EUR", "USD"),
    "GBPUSD": (5, 0.00001, 100_000.0, "GBP", "USD"),
    "USDJPY": (3, 0.001, 100_000.0, "USD", "JPY"),
    "AUDUSD": (5, 0.00001, 100_000.0, "AUD", "USD"),
    "USDCAD": (5, 0.00001, 100_000.0, "USD", "CAD"),
    "USDCHF": (5, 0.00001, 100_000.0, "USD", "CHF"),
    "EURJPY": (3, 0.001, 100_000.0, "EUR", "JPY"),
    "GBPJPY": (3, 0.001, 100_000.0, "GBP", "JPY"),
}


def indicative_spec(symbol: str, account_currency: str = "EUR", rates_to_eur: dict | None = None) -> SymbolSpec:
    """Spécification INDICATIVE (non contractuelle) pour le mode hors-ligne."""
    if symbol not in _INDICATIVE:
        raise KeyError(f"Pas de spécification indicative pour {symbol}")
    if account_currency != "EUR":
        raise NotImplementedError("Mode hors-ligne : seule la devise de compte EUR est gérée.")
    rates = rates_to_eur or DEFAULT_RATES_TO_EUR
    digits, point, contract, base, profit = _INDICATIVE[symbol]
    tick_size = point
    tick_value = contract * tick_size * rates[profit]
    return SymbolSpec(
        name=symbol, digits=digits, point=point, contract_size=contract,
        volume_min=0.01, volume_step=0.01, volume_max=50.0,
        tick_size=tick_size, tick_value=tick_value,
        base_currency=base, profit_currency=profit, source="indicatif",
    )


# Levier maximum pour les clients PARTICULIERS dans l'UE (décision ESMA, reprise par l'AMF) :
# 1:30 paires de devises majeures, 1:20 or et autres paires. Le broker peut appliquer moins.
_ESMA_MAJORS = {"EUR", "USD", "JPY", "GBP", "CAD", "CHF"}


def esma_retail_leverage(symbol: str) -> int:
    if symbol.startswith("XAU"):
        return 20
    base, quote = symbol[:3], symbol[3:6]
    return 30 if base in _ESMA_MAJORS and quote in _ESMA_MAJORS else 20


def margin_required(spec: SymbolSpec, lots: float, price: float, leverage: float,
                    rates_to_eur: dict | None = None) -> float:
    """Marge approximative en EUR : notionnel / levier.

    MT5 fournit la valeur exacte via order_calc_margin ; cette formule est utilisée
    hors-ligne et comme contrôle de cohérence.
    """
    rates = rates_to_eur or DEFAULT_RATES_TO_EUR
    notional_profit_ccy = lots * spec.contract_size * price
    if spec.base_currency in rates:
        notional_eur = lots * spec.contract_size * rates[spec.base_currency]
    else:  # XAU : notionnel en USD (devise de cotation)
        notional_eur = notional_profit_ccy * rates[spec.profit_currency]
    return notional_eur / leverage
