"""Portefeuille : positions ouvertes, historique des trades, gains/pertes,
dépôts/retraits et jauges de gestion du risque.

Les données viennent de MetaTrader 5 (historique officiel du broker). Le robot
ne peut PAS retirer d'argent : un retrait se fait uniquement dans l'espace
client du broker. Ce module se contente d'afficher les mouvements et d'estimer
l'effet d'un retrait sur la gestion du risque.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from ..data import mt5_client
from ..data.symbol_spec import SymbolSpec
from ..risk.guards import AccountState

# Constantes de l'API MetaTrader 5 (valeurs officielles)
DEAL_TYPE_BUY, DEAL_TYPE_SELL, DEAL_TYPE_BALANCE = 0, 1, 2
DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY = 0, 1, 2, 3
POSITION_TYPE_BUY = 0

POSITION_COLUMNS = ["ticket", "symbole", "sens", "lots", "ouverture", "prix_entree", "prix_actuel", "sl", "tp",
                    "pnl_eur", "risque_sl_eur", "gain_tp_eur", "robot", "duree"]
TRADE_COLUMNS = ["position", "symbole", "sens", "lots", "ouverture", "fermeture", "prix_entree", "prix_sortie",
                 "brut_eur", "frais_eur", "pnl_eur", "robot"]


def _strip(symbol: str, suffix: str) -> str:
    return symbol[: -len(suffix)] if suffix and symbol.endswith(suffix) else symbol


def _ts(seconds: int, offset_s: int) -> pd.Timestamp:
    return pd.Timestamp(seconds - offset_s, unit="s", tz="UTC")


# ---------------------------------------------------------------- positions ouvertes
def open_positions(client, specs: dict[str, SymbolSpec], magic: int, now: datetime | None = None) -> pd.DataFrame:
    mt5 = mt5_client.mt5
    raw = mt5.positions_get() or []
    offset = client.server_utc_offset_seconds()
    now_ts = pd.Timestamp(now or datetime.now(timezone.utc))
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    rows = []
    for p in raw:
        sym = _strip(p.symbol, client.suffix)
        spec = specs.get(sym)
        buy = p.type == POSITION_TYPE_BUY
        risk = gain = None
        if spec is not None:
            if p.sl:
                # perte si le SL est touché, depuis le prix d'ENTRÉE (négatif si le SL est déjà en gain)
                risk = spec.money_for_distance(abs(p.price_open - p.sl), p.volume) * (
                    1 if (buy and p.sl < p.price_open) or (not buy and p.sl > p.price_open) else -1)
            if p.tp:
                gain = spec.money_for_distance(abs(p.tp - p.price_open), p.volume)
        opened = _ts(p.time, offset)
        rows.append({"ticket": p.ticket, "symbole": sym, "sens": "ACHAT" if buy else "VENTE", "lots": p.volume,
                     "ouverture": opened, "prix_entree": p.price_open, "prix_actuel": p.price_current,
                     "sl": p.sl or None, "tp": p.tp or None, "pnl_eur": p.profit + p.swap,
                     "risque_sl_eur": risk, "gain_tp_eur": gain, "robot": p.magic == magic,
                     "duree": _duration(now_ts - opened)})
    return pd.DataFrame(rows, columns=POSITION_COLUMNS)


def _duration(td: pd.Timedelta) -> str:
    mins = max(0, int(td.total_seconds() // 60))
    return f"{mins // 1440}j {mins % 1440 // 60}h{mins % 60:02d}" if mins >= 1440 else f"{mins // 60}h{mins % 60:02d}"


# ---------------------------------------------------------------- historique
def closed_trades(client, start: datetime, end: datetime, magic: int) -> pd.DataFrame:
    """Trades clôturés, reconstitués à partir des transactions (deals) MT5."""
    mt5 = mt5_client.mt5
    deals = mt5.history_deals_get(start, end) or []
    offset = client.server_utc_offset_seconds()
    by_pos: dict[int, list] = {}
    for d in deals:
        if d.type in (DEAL_TYPE_BUY, DEAL_TYPE_SELL):
            by_pos.setdefault(d.position_id, []).append(d)
    rows = []
    for pos_id, ds in by_pos.items():
        ins = [d for d in ds if d.entry == DEAL_ENTRY_IN]
        outs = [d for d in ds if d.entry in (DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY, DEAL_ENTRY_INOUT)]
        if not outs:
            continue  # position encore ouverte
        first_in = ins[0] if ins else None
        vol_out = sum(d.volume for d in outs)
        exit_price = sum(d.price * d.volume for d in outs) / vol_out if vol_out else outs[-1].price
        gross = sum(d.profit for d in ds)
        fees = sum(d.commission + d.swap + getattr(d, "fee", 0.0) for d in ds)
        direction = (first_in.type if first_in else 1 - outs[0].type)
        rows.append({"position": pos_id, "symbole": _strip(ds[0].symbol, client.suffix),
                     "sens": "ACHAT" if direction == DEAL_TYPE_BUY else "VENTE", "lots": vol_out,
                     "ouverture": _ts(first_in.time, offset) if first_in else pd.NaT,
                     "fermeture": _ts(max(d.time for d in outs), offset),
                     "prix_entree": first_in.price if first_in else None, "prix_sortie": exit_price,
                     "brut_eur": gross, "frais_eur": fees, "pnl_eur": gross + fees,
                     "robot": any(d.magic == magic for d in ds)})
    df = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    return df.sort_values("fermeture").reset_index(drop=True)


def cash_movements(client, start: datetime, end: datetime) -> pd.DataFrame:
    """Dépôts et retraits enregistrés par le broker."""
    mt5 = mt5_client.mt5
    offset = client.server_utc_offset_seconds()
    rows = [{"date": _ts(d.time, offset), "type": "Dépôt" if d.profit > 0 else "Retrait", "montant_eur": d.profit,
             "commentaire": d.comment}
            for d in (mt5.history_deals_get(start, end) or []) if d.type == DEAL_TYPE_BALANCE]
    return pd.DataFrame(rows, columns=["date", "type", "montant_eur", "commentaire"])


# ---------------------------------------------------------------- statistiques
@dataclass
class PnLSummary:
    trades: int
    pnl_net: float
    gains: float
    pertes: float
    frais: float
    gagnants: int
    perdants: int
    win_rate: float
    meilleur: float
    pire: float
    profit_factor: float


def summarize(trades: pd.DataFrame) -> PnLSummary:
    if trades.empty:
        return PnLSummary(0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0, 0.0, 0.0)
    p = trades["pnl_eur"]
    gains, losses = p[p > 0].sum(), p[p <= 0].sum()
    return PnLSummary(trades=len(p), pnl_net=float(p.sum()), gains=float(gains), pertes=float(losses),
                      frais=float(trades["frais_eur"].sum()), gagnants=int((p > 0).sum()), perdants=int((p <= 0).sum()),
                      win_rate=float((p > 0).mean() * 100), meilleur=float(p.max()), pire=float(p.min()),
                      profit_factor=float(gains / -losses) if losses < 0 else float("inf"))


def by_instrument(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["symbole", "trades", "pnl_eur", "gains", "pertes", "win_rate"])
    g = trades.groupby("symbole")["pnl_eur"]
    out = pd.DataFrame({"trades": g.size(), "pnl_eur": g.sum(), "gains": g.apply(lambda s: s[s > 0].sum()),
                        "pertes": g.apply(lambda s: s[s <= 0].sum()), "win_rate": g.apply(lambda s: (s > 0).mean() * 100)})
    return out.reset_index().sort_values("pnl_eur", ascending=False)


def daily_pnl(trades: pd.DataFrame, tz: str = "Europe/Paris") -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["jour", "pnl_eur", "trades"])
    t = trades.assign(jour=trades["fermeture"].dt.tz_convert(tz).dt.date)
    return t.groupby("jour").agg(pnl_eur=("pnl_eur", "sum"), trades=("pnl_eur", "size")).reset_index()


# ---------------------------------------------------------------- jauges de risque
@dataclass
class Gauge:
    nom: str
    utilise: float      # valeur actuelle (en % ou en nombre)
    limite: float
    unite: str
    detail: str = ""

    @property
    def ratio(self) -> float:
        return max(0.0, min(1.0, self.utilise / self.limite)) if self.limite else 0.0

    @property
    def niveau(self) -> str:
        return "danger" if self.ratio >= 1 else ("attention" if self.ratio >= 0.7 else "ok")


def risk_gauges(state: AccountState, risk_cfg: dict, positions: pd.DataFrame) -> list[Gauge]:
    bal = state.balance or 1.0
    day_loss = max(0.0, (state.start_of_day_balance - state.equity) / state.start_of_day_balance * 100)
    week_loss = max(0.0, (state.start_of_week_balance - state.equity) / state.start_of_week_balance * 100)
    dd = max(0.0, (state.peak_equity - state.equity) / state.peak_equity * 100) if state.peak_equity else 0.0
    open_risk = float(positions["risque_sl_eur"].fillna(0).clip(lower=0).sum()) if not positions.empty else 0.0
    no_sl = int(positions["sl"].isna().sum()) if not positions.empty else 0
    max_exposure = float(risk_cfg["risque_par_trade_pct"]) * int(risk_cfg["positions_simultanees_max"])
    return [
        Gauge("Perte du jour", day_loss, float(risk_cfg["perte_max_jour_pct"]), "%",
              f"{state.start_of_day_balance - state.equity:+.2f} € depuis le début de journée".replace("+-", "-")),
        Gauge("Perte de la semaine", week_loss, float(risk_cfg["perte_max_semaine_pct"]), "%"),
        Gauge("Drawdown depuis le plus haut", dd, float(risk_cfg["drawdown_max_pct"]), "%",
              f"plus haut : {state.peak_equity:.2f} €"),
        Gauge("Risque ouvert (si tous les SL sont touchés)", open_risk / bal * 100, max_exposure, "%",
              f"{open_risk:.2f} €" + (f" — ⚠️ {no_sl} position(s) SANS stop loss" if no_sl else "")),
        Gauge("Positions ouvertes", float(state.open_positions), float(risk_cfg["positions_simultanees_max"]), ""),
        Gauge("Trades aujourd'hui", float(state.trades_today), float(risk_cfg["trades_max_par_jour"]), ""),
    ]


# ---------------------------------------------------------------- retraits
@dataclass
class WithdrawalImpact:
    montant: float
    capital_apres: float
    risque_trade_avant: float
    risque_trade_apres: float
    marge_utilisee_pct_apres: float
    possible: bool
    messages: list[str]


def withdrawal_impact(balance: float, equity: float, margin_used: float, amount: float, risk_pct: float,
                      min_lot_risk_eur: dict[str, float] | None = None) -> WithdrawalImpact:
    """Estime l'effet d'un retrait sur le capital, le risque par trade et la marge."""
    msgs: list[str] = []
    after = balance - amount
    free_after = equity - amount - margin_used
    possible = amount > 0 and free_after > 0 and after > 0
    if amount <= 0:
        msgs.append("Indiquez un montant positif.")
    elif free_after <= 0:
        msgs.append("Retrait impossible : la marge libre ne suffit pas tant que des positions sont ouvertes. "
                    "Fermez ou laissez se clôturer les positions d'abord.")
    margin_pct_after = margin_used / (equity - amount) * 100 if equity - amount > 0 else float("inf")
    if possible and margin_pct_after > 50:
        msgs.append(f"Après retrait, la marge utilisée représenterait {margin_pct_after:.0f} % du capital : risque "
                    "de clôture forcée par le broker.")
    if possible:
        msgs.append(f"Le risque par trade passera de {balance * risk_pct / 100:.2f} € à {after * risk_pct / 100:.2f} € "
                    f"(toujours {risk_pct} % du capital).")
        for sym, r in (min_lot_risk_eur or {}).items():
            if r > after * risk_pct / 100:
                msgs.append(f"{sym} : le lot minimum risquerait {r:.2f} €, au-delà de la nouvelle limite → "
                            "le robot refusera ces trades.")
    return WithdrawalImpact(amount, after, balance * risk_pct / 100, after * risk_pct / 100, margin_pct_after,
                            possible, msgs)


# ---------------------------------------------------------------- exemple fictif (mode simulation)
def example_from_backtest(bt_trades: pd.DataFrame) -> pd.DataFrame:
    """Convertit des trades de backtest SIMULÉ au format de l'historique (pour visualiser l'interface)."""
    if bt_trades.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    return pd.DataFrame({
        "position": range(1, len(bt_trades) + 1), "symbole": bt_trades["symbol"],
        "sens": bt_trades["direction"].map({"BUY": "ACHAT", "SELL": "VENTE"}), "lots": bt_trades["lots"],
        "ouverture": bt_trades["entry_time"], "fermeture": bt_trades["exit_time"], "prix_entree": bt_trades["entry"],
        "prix_sortie": bt_trades["exit"], "brut_eur": bt_trades["gross"],
        "frais_eur": -bt_trades["commission"] + bt_trades["swap"], "pnl_eur": bt_trades["pnl"], "robot": True,
    })[TRADE_COLUMNS]
