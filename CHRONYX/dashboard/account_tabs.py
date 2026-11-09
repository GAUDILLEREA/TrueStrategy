"""Écrans « Positions & résultats », « Gestion du risque » et « Pause & retraits »."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from chronyx.account import portfolio as pf
from chronyx.backtest.engine import BacktestConfig, run_backtest
from chronyx.config import Config
from chronyx.data.storage import Storage
from chronyx.execution.executor import MAGIC, OrderRefused, close_all_positions, close_position
from chronyx.risk.guards import (AccountState, activate_pause, kill_switch_active, pause_active, pause_info,
                                 release_pause)
from chronyx.strategies.trend_scalping import TrendScalping
from charts import cumulative_pnl_chart, daily_pnl_chart, instrument_pnl_chart

PERIODS = {"Aujourd'hui": 0, "7 derniers jours": 7, "30 derniers jours": 30, "Depuis le début": 3650}


def eur(x: float | None) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:,.2f} €".replace(",", " ")


@dataclass
class Ctx:
    cfg: Config
    source: object
    storage: Storage
    account: dict
    now: datetime

    @property
    def live(self) -> bool:
        return bool(self.source.live)


# ---------------------------------------------------------------- données
def _period_start(now: datetime, label: str) -> datetime:
    days = PERIODS[label]
    local_midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return (local_midnight - timedelta(days=days)).astimezone(timezone.utc)


@st.cache_data(ttl=3600, show_spinner=False)
def _example_trades(capital: float) -> pd.DataFrame:
    """Historique FICTIF issu d'un backtest simulé, uniquement pour visualiser l'interface."""
    from chronyx.data.sample_data import generate_ohlc, resample
    from chronyx.data.symbol_spec import indicative_spec
    frames = []
    for i, (sym, spread) in enumerate((("EURUSD", 8), ("GBPUSD", 12), ("XAUUSD", 25))):
        df = generate_ohlc(sym, "M5", 4000, seed=100 + i, spread_points=spread,
                           end=pd.Timestamp.now(tz="UTC").floor("5min"))
        p = TrendScalping().prepare(df, resample(df, "H1"))
        r = run_backtest(p, indicative_spec(sym), BacktestConfig(initial_balance=max(capital, 500), risk_pct=1.0,
                                                                  max_margin_pct=100), strategy_name="A")
        frames.append(r.trades)
    return pf.example_from_backtest(pd.concat(frames).sort_values("exit_time").tail(60))


def _history(ctx: Ctx, start: datetime, show_example: bool) -> tuple[pd.DataFrame, bool]:
    if ctx.live:
        return pf.closed_trades(ctx.source.client, start, ctx.now + timedelta(days=1), MAGIC), False
    if show_example:
        t = _example_trades(float(ctx.cfg.get("capital", "capital_initial")))
        return t[t["fermeture"] >= pd.Timestamp(start)], True
    return pd.DataFrame(columns=pf.TRADE_COLUMNS), False


def _positions(ctx: Ctx) -> pd.DataFrame:
    if not ctx.live:
        return pd.DataFrame(columns=pf.POSITION_COLUMNS)
    from chronyx.data import mt5_client
    raw = mt5_client.mt5.positions_get() or []
    specs = {}
    for p in raw:
        sym = pf._strip(p.symbol, ctx.source.client.suffix, ctx.source.client._symbol_map)
        try:
            specs[sym] = ctx.source.spec(sym)
        except Exception:
            pass
    return pf.open_positions(ctx.source.client, specs, MAGIC, ctx.now)


def _tracked_state(ctx: Ctx, positions: pd.DataFrame) -> AccountState:
    """État du compte pour les jauges : début de journée/semaine reconstitué depuis l'historique MT5,
    plus haut d'equity mémorisé par le moteur (data/etat_compte.json)."""
    bal, eq = float(ctx.account["balance"]), float(ctx.account["equity"])
    day_start, week_start = bal, bal
    if ctx.live:
        today = pf.closed_trades(ctx.source.client, _period_start(ctx.now, "Aujourd'hui"), ctx.now + timedelta(days=1), MAGIC)
        monday = ctx.now.astimezone() - timedelta(days=ctx.now.astimezone().weekday())
        week = pf.closed_trades(ctx.source.client, monday.replace(hour=0, minute=0, second=0), ctx.now + timedelta(days=1), MAGIC)
        day_start = bal - float(today["pnl_eur"].sum())
        week_start = bal - float(week["pnl_eur"].sum())
    peak = max(bal, eq)
    trades_today = 0
    from chronyx.engine.bot import STATE_FILE
    if STATE_FILE.exists():
        try:
            d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            peak = max(peak, float(d.get("peak", peak)))
            trades_today = int(d.get("trades_today", 0)) if d.get("day") == ctx.now.date().isoformat() else 0
        except (ValueError, OSError):
            pass
    robot_pos = positions[positions["robot"]] if not positions.empty else positions
    return AccountState(balance=bal, equity=eq, start_of_day_balance=day_start, start_of_week_balance=week_start,
                        peak_equity=peak, trades_today=trades_today, open_positions=len(robot_pos),
                        open_symbols=set(robot_pos["symbole"]) if not robot_pos.empty else set())


def _status_banner() -> None:
    if kill_switch_active():
        st.error("⛔ **STOP GLOBAL ACTIF** — le robot est arrêté et ferme ses positions.")
    elif pause_active():
        st.warning(f"⏸️ **ROBOT EN PAUSE** depuis {pause_info()} — aucune nouvelle position ; "
                   "les positions ouvertes restent protégées par leur SL/TP.")
    else:
        st.success("🟢 **ROBOT ACTIF** — il peut ouvrir des positions selon le mode choisi et les protections.")


# ================================================================ POSITIONS & RÉSULTATS
def render_positions(ctx: Ctx) -> None:
    _status_banner()
    st.subheader("Positions ouvertes")
    pos = _positions(ctx)
    if not ctx.live:
        st.info("Mode SIMULATION : aucune position réelle. Connectez MetaTrader 5 (compte démo) pour voir vos positions.")
    elif pos.empty:
        st.info("Aucune position ouverte.")
    else:
        k = st.columns(4)
        k[0].metric("Positions", len(pos))
        k[1].metric("P&L latent", eur(pos["pnl_eur"].sum()))
        k[2].metric("Risque total si tous les SL sont touchés", eur(pos["risque_sl_eur"].fillna(0).clip(lower=0).sum()))
        k[3].metric("Gain total si tous les TP sont atteints", eur(pos["gain_tp_eur"].fillna(0).sum()))
        if pos["sl"].isna().any():
            st.error("⚠️ Au moins une position n'a PAS de stop loss : risque illimité. Ajoutez un SL dans MT5 ou fermez-la.")
        show = pos.assign(sens=pos["sens"], ouverture=pos["ouverture"].dt.tz_convert("Europe/Paris").dt.strftime("%d/%m %H:%M"),
                          robot=pos["robot"].map({True: "CHRONYX", False: "Manuel"}))
        st.dataframe(show.rename(columns={"pnl_eur": "P&L (€)", "risque_sl_eur": "Perte au SL (€)",
                                          "gain_tp_eur": "Gain au TP (€)", "prix_entree": "Entrée",
                                          "prix_actuel": "Actuel", "robot": "Ouvert par"}),
                     hide_index=True, width="stretch",
                     column_config={"P&L (€)": st.column_config.NumberColumn(format="%.2f €")})
        st.markdown("**Fermer une position**")
        c = st.columns([3, 1])
        labels = {int(r.ticket): f"#{r.ticket} · {r.sens} {r.lots} {r.symbole} · P&L {eur(r.pnl_eur)}" for r in pos.itertuples()}
        ticket = c[0].selectbox("Position", list(labels), format_func=labels.get, label_visibility="collapsed")
        if c[1].button("Fermer cette position", type="primary"):
            try:
                close_position(ctx.source.client, ctx.storage, ticket)
                st.success(f"Position #{ticket} fermée.")
                st.rerun()
            except OrderRefused as e:
                st.error(str(e))

    st.divider()
    st.subheader("Résultats : gains et pertes")
    c = st.columns([2, 2, 3])
    period = c[0].selectbox("Période", list(PERIODS), index=1)
    who = c[1].selectbox("Trades", ["Tous", "CHRONYX uniquement", "Manuels uniquement"])
    show_example = False
    if not ctx.live:
        show_example = c[2].toggle("Afficher un EXEMPLE fictif (pour découvrir l'interface)", value=True)
    trades, is_example = _history(ctx, _period_start(ctx.now, period), show_example)
    if who == "CHRONYX uniquement":
        trades = trades[trades["robot"]]
    elif who == "Manuels uniquement":
        trades = trades[~trades["robot"].astype(bool)]
    if is_example:
        st.error("⚠️ EXEMPLE FICTIF : trades issus d'un backtest sur données simulées. Ce ne sont PAS vos résultats.")
    if trades.empty:
        st.info("Aucun trade clôturé sur cette période.")
        return

    s = pf.summarize(trades)
    k = st.columns(3)
    k[0].metric("Résultat net", eur(s.pnl_net))
    k[1].metric("Total des gains", eur(s.gains))
    k[2].metric("Total des pertes", eur(s.pertes))
    k = st.columns(3)
    k[0].metric("Trades gagnants / perdants", f"{s.gagnants} / {s.perdants}", f"{s.win_rate:.0f} % gagnants",
                delta_color="off")
    k[1].metric("Profit factor", "∞" if s.profit_factor == float("inf") else f"{s.profit_factor:.2f}")
    k[2].metric("Frais (commissions + swaps)", eur(s.frais))
    k = st.columns(3)
    k[0].metric("Meilleur trade", eur(s.meilleur))
    k[1].metric("Pire trade", eur(s.pire))
    k[2].metric("Nombre de trades", s.trades)

    left, right = st.columns(2)
    left.plotly_chart(cumulative_pnl_chart(trades), width="stretch")
    right.plotly_chart(daily_pnl_chart(pf.daily_pnl(trades)), width="stretch")

    st.markdown("#### Instruments tradés")
    inst = pf.by_instrument(trades)
    left, right = st.columns([3, 2])
    left.plotly_chart(instrument_pnl_chart(inst), width="stretch")
    right.dataframe(inst.rename(columns={"symbole": "Instrument", "trades": "Trades", "pnl_eur": "Net (€)",
                                         "gains": "Gains (€)", "pertes": "Pertes (€)", "win_rate": "% gagnants"}),
                    hide_index=True, width="stretch",
                    column_config={c: st.column_config.NumberColumn(format="%.2f") for c in
                                   ("Net (€)", "Gains (€)", "Pertes (€)", "% gagnants")})

    st.markdown("#### Historique des trades")
    h = trades.sort_values("fermeture", ascending=False).copy()
    for col in ("ouverture", "fermeture"):
        h[col] = pd.to_datetime(h[col]).dt.tz_convert("Europe/Paris").dt.strftime("%d/%m %H:%M")
    h["résultat"] = h["pnl_eur"].map(lambda v: "✅ Gain" if v > 0 else "❌ Perte")
    h["robot"] = h["robot"].map({True: "CHRONYX", False: "Manuel"})
    st.dataframe(h[["résultat", "fermeture", "symbole", "sens", "lots", "prix_entree", "prix_sortie", "pnl_eur",
                    "frais_eur", "ouverture", "robot"]].rename(columns={"pnl_eur": "P&L net (€)", "frais_eur": "Frais (€)"}),
                 hide_index=True, width="stretch",
                 column_config={"P&L net (€)": st.column_config.NumberColumn(format="%.2f €")})
    st.download_button("⬇️ Exporter l'historique (CSV)", trades.to_csv(index=False).encode("utf-8-sig"),
                       "chronyx_historique.csv", "text/csv")


# ================================================================ GESTION DU RISQUE
def render_risk(ctx: Ctx) -> None:
    _status_banner()
    pos = _positions(ctx)
    state = _tracked_state(ctx, pos)
    r = ctx.cfg.risk
    st.subheader("Gestion du risque — où en êtes-vous par rapport à vos limites ?")
    if not ctx.live:
        st.info("Mode SIMULATION : jauges calculées sur le capital de référence, sans position réelle.")

    k = st.columns(4)
    k[0].metric("Balance", eur(state.balance))
    k[1].metric("Equity", eur(state.equity), eur(state.equity - state.balance))
    k[2].metric("Risque par trade", f"{r['risque_par_trade_pct']} %", eur(state.balance * r["risque_par_trade_pct"] / 100),
                delta_color="off")
    k[3].metric("Risk/Reward visé", f"1:{r['risk_reward']}")

    st.markdown("#### Jauges des limites")
    icons = {"ok": "🟢", "attention": "🟠", "danger": "🔴"}
    for g in pf.risk_gauges(state, r, pos):
        c = st.columns([3, 5, 2])
        unit = f" {g.unite}" if g.unite else ""
        c[0].markdown(f"{icons[g.niveau]} **{g.nom}**" + (f"  \n<small>{g.detail}</small>" if g.detail else ""),
                      unsafe_allow_html=True)
        c[1].progress(g.ratio)
        c[2].markdown(f"**{g.utilise:.2f}{unit}** / {g.limite:g}{unit}" if g.unite else
                      f"**{g.utilise:.0f}** / {g.limite:g}")
    st.caption("🟢 sous 70 % de la limite · 🟠 entre 70 et 100 % · 🔴 limite atteinte : le robot n'ouvre plus de position.")

    st.markdown("#### Règles actives")
    rules = pd.DataFrame([
        ("Risque maximum par trade", f"{r['risque_par_trade_pct']} % du capital (plafond absolu 2 %)"),
        ("Stop loss", f"{r['stop_loss_atr_mult']} × ATR, envoyé au broker avec chaque ordre"),
        ("Take profit", f"Stop × {r['risk_reward']}"),
        ("Break-even", f"à +{r['break_even_r']} R" if r["break_even_r"] else "désactivé"),
        ("Perte max par jour / semaine", f"{r['perte_max_jour_pct']} % / {r['perte_max_semaine_pct']} %"),
        ("Drawdown max", f"{r['drawdown_max_pct']} % → STOP GLOBAL automatique"),
        ("Positions simultanées max", str(r["positions_simultanees_max"])),
        ("Trades max par jour", str(r["trades_max_par_jour"])),
        ("Pause après une perte", f"{r['pause_apres_perte_min']} min"),
        ("Martingale / grid / récupération des pertes", "INTERDITS"),
    ], columns=["Règle", "Valeur"])
    st.table(rules.set_index("Règle"))
    st.caption("Ces valeurs se modifient dans l'onglet ⚙️ Paramètres.")


# ================================================================ PAUSE & RETRAITS
def render_pause(ctx: Ctx) -> None:
    _status_banner()
    st.subheader("⏸️ Mettre le robot en pause")
    c = st.columns(2)
    with c[0]:
        st.markdown("**PAUSE** : le robot n'ouvre plus aucune position. Les positions déjà ouvertes **restent ouvertes**, "
                    "protégées par leur stop loss et take profit chez le broker. Idéal avant un retrait, des vacances, "
                    "une période d'annonces ou simplement pour souffler.")
        if pause_active():
            if st.button("▶️ Reprendre le trading", type="primary", disabled=kill_switch_active()):
                release_pause()
                ctx.storage.log_event("INFO", "pause", "Reprise du trading depuis le dashboard")
                st.rerun()
        else:
            reason = st.text_input("Motif (facultatif)", placeholder="ex. retrait, vacances, annonces Fed…")
            if st.button("⏸️ Mettre en pause", type="primary"):
                activate_pause(reason or "pause manuelle")
                ctx.storage.log_event("INFO", "pause", f"Robot mis en pause : {reason or 'pause manuelle'}")
                st.rerun()
    with c[1]:
        st.markdown("**FERMER TOUTES LES POSITIONS CHRONYX** (sans arrêter le robot). Pour tout arrêter "
                    "définitivement, utilisez ⛔ STOP GLOBAL dans la barre latérale.")
        sure = st.checkbox("Je confirme vouloir fermer toutes les positions ouvertes par CHRONYX au prix du marché")
        if st.button("Fermer toutes les positions", disabled=not (sure and ctx.live)):
            n = close_all_positions(ctx.source.client, ctx.storage)
            st.success(f"{n} position(s) fermée(s).")
        if not ctx.live:
            st.caption("Disponible uniquement avec MetaTrader 5 connecté.")

    st.divider()
    st.subheader("💶 Retirer de l'argent")
    st.info("🔒 **Par sécurité, CHRONYX ne peut pas retirer ni déplacer votre argent.** Un retrait se fait uniquement "
            "dans l'espace client de votre broker (site web ou application), vers le moyen de paiement utilisé pour le dépôt.")
    st.markdown("""**Procédure conseillée**
1. Cliquer sur **⏸️ Mettre en pause** ci-dessus.
2. Attendre que les positions se clôturent (SL/TP) ou les fermer : un retrait avec des positions ouvertes réduit la
   marge disponible et peut provoquer une clôture forcée.
3. Se connecter à l'espace client du broker → *Retrait* → choisir le montant. Vérifier les frais et délais du broker.
4. Une fois le retrait reçu, mettre à jour le **capital de référence** (onglet ⚙️ Paramètres) si nécessaire.
5. Vérifier l'onglet **💶 Capital & faisabilité** : avec moins de capital, certains instruments peuvent devenir non tradables.
6. Cliquer sur **▶️ Reprendre le trading**.""")

    st.markdown("#### Simuler l'effet d'un retrait")
    bal, eq = float(ctx.account["balance"]), float(ctx.account["equity"])
    margin_used = float(ctx.account.get("margin", 0.0) or 0.0)
    amount = st.number_input("Montant du retrait envisagé (€)", 0.0, max(bal, 1.0), min(50.0, bal), 10.0)
    min_lot = {}
    for sym in ctx.cfg.active_symbols:
        try:
            spec = ctx.source.spec(sym)
            from chronyx.analysis.indicators import atr
            a = float(atr(ctx.source.rates(sym, ctx.cfg.get("timeframes", "principal", default="M5")), 14).iloc[-200:].median())
            min_lot[sym] = spec.money_for_distance(a * float(ctx.cfg.risk["stop_loss_atr_mult"]), spec.volume_min)
        except Exception:
            pass
    imp = pf.withdrawal_impact(bal, eq, margin_used, amount, float(ctx.cfg.risk["risque_par_trade_pct"]), min_lot)
    k = st.columns(3)
    k[0].metric("Capital après retrait", eur(imp.capital_apres), eur(-amount))
    k[1].metric("Risque par trade après", eur(imp.risque_trade_apres), eur(imp.risque_trade_apres - imp.risque_trade_avant))
    k[2].metric("Retrait possible maintenant", "Oui" if imp.possible else "Non")
    for m in imp.messages:
        (st.warning if ("impossible" in m or "refusera" in m or "forcée" in m) else st.write)(m)

    st.markdown("#### Dépôts et retraits enregistrés chez le broker")
    if ctx.live:
        mv = pf.cash_movements(ctx.source.client, ctx.now - timedelta(days=3650), ctx.now + timedelta(days=1))
        if mv.empty:
            st.caption("Aucun mouvement trouvé dans l'historique MT5.")
        else:
            dep = mv.loc[mv["montant_eur"] > 0, "montant_eur"].sum()
            wd = -mv.loc[mv["montant_eur"] < 0, "montant_eur"].sum()
            k = st.columns(4)
            k[0].metric("Total déposé", eur(dep))
            k[1].metric("Total retiré", eur(wd))
            k[2].metric("Capital actuel (equity)", eur(eq))
            k[3].metric("Résultat réel du trading", eur(eq - dep + wd),
                        help="Equity − dépôts + retraits : ce que le trading a réellement gagné ou perdu.")
            mv["date"] = mv["date"].dt.tz_convert("Europe/Paris").dt.strftime("%d/%m/%Y %H:%M")
            st.dataframe(mv, hide_index=True, width="stretch")
    else:
        st.caption("Disponible avec MetaTrader 5 connecté (historique officiel du broker).")
