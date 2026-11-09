"""CHRONYX AI TRADING BOT - Dashboard (Streamlit).

Lancement : start_bot.bat  (ou : streamlit run dashboard/app.py)
Le dashboard sert à SURVEILLER et CONFIGURER. Les protections du compte sont
appliquées par le moteur (chronyx/engine/bot.py) et par les SL/TP côté broker,
même si le dashboard est fermé.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from chronyx import __version__  # noqa: E402
from chronyx.backtest.engine import BacktestConfig, run_backtest, run_periods  # noqa: E402
from chronyx.backtest.metrics import robustness_score  # noqa: E402
from chronyx.brokers.comparison import comparison_table, load_brokers  # noqa: E402
from chronyx.config import load_config, validate  # noqa: E402
from chronyx.data.storage import Storage  # noqa: E402
from chronyx.engine.pipeline import analyze, default_account_state  # noqa: E402
from chronyx.engine.sources import make_source  # noqa: E402
from chronyx.execution.modes import (CONFIRMATION_PHRASE, Mode, order_gate, revoke_real_confirmation,  # noqa: E402
                                     risk_fingerprint, write_real_confirmation)
from chronyx.news.calendar import load_calendar, news_mask  # noqa: E402
from chronyx.risk.feasibility import assess  # noqa: E402
from chronyx.risk.guards import activate_kill_switch, kill_switch_active, release_kill_switch  # noqa: E402
from chronyx.strategies.registry import IMPLEMENTED, PLANNED, build  # noqa: E402
from charts import equity_chart, price_chart  # noqa: E402

st.set_page_config(page_title="CHRONYX AI Trading Bot", page_icon="⚡", layout="wide")
st.markdown("""<style>
div[data-testid="stMetric"]{background:#161B26;border:1px solid #232A38;border-radius:8px;padding:10px 14px}
.block-container{padding-top:1.2rem}
.chx-ok{color:#26A69A;font-weight:600}.chx-ko{color:#EF5350;font-weight:600}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- ressources
@st.cache_resource(show_spinner="Connexion aux données...")
def get_source(prefer_mt5: bool):
    return make_source(load_config(), prefer_mt5)


def eur(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ")


cfg = load_config()
storage = Storage(cfg.path_for(cfg.get("journal", "base_sqlite", default="data/chronyx.db")))

# ---------------------------------------------------------------- barre latérale
with st.sidebar:
    st.markdown(f"## ⚡ CHRONYX\nAI Trading Bot · v{__version__}")
    prefer_mt5 = st.toggle("Connexion MetaTrader 5", value=True,
                           help="Désactivé = données simulées (test de l'installation).")
    source, source_msg = get_source(prefer_mt5)
    if st.button("🔄 Reconnecter / rafraîchir"):
        get_source.clear()
        st.rerun()
    mode = Mode(cfg.mode)
    st.markdown(f"**Mode :** {mode.label}")
    st.markdown(f"**Source :** {source.name}")
    st.divider()
    if kill_switch_active():
        st.error("⛔ STOP GLOBAL ACTIF")
        if st.button("Lever le STOP GLOBAL"):
            release_kill_switch()
            storage.log_event("WARNING", "stop_global", "STOP GLOBAL levé manuellement")
            st.rerun()
    else:
        if st.button("⛔ STOP GLOBAL", type="primary", width="stretch",
                     help="Bloque toute nouvelle position. Le moteur ferme les positions CHRONYX."):
            activate_kill_switch("Bouton STOP GLOBAL du dashboard")
            storage.log_event("CRITICAL", "stop_global", "STOP GLOBAL activé depuis le dashboard")
            st.rerun()
    st.caption("Aucun conseil en investissement. Le trading comporte un risque de perte en capital.")

if source_msg:
    st.warning(source_msg)
for w in cfg.warnings:
    st.warning(w)

account = source.account()
state = default_account_state(account)
now = datetime.now(timezone.utc)
cal_cfg = cfg.get("calendrier", default={}) or {}
calendar = load_calendar(cfg.path_for(cal_cfg.get("fichier", "data/calendrier.csv")),
                         float(cal_cfg.get("age_max_heures", 24)), now)

tabs = st.tabs(["🏠 Tableau de bord", "📈 Analyse en direct", "💶 Capital & faisabilité", "🧪 Backtest",
                "🏦 Brokers", "📚 Stratégies", "⚙️ Paramètres", "📜 Journal"])

# ================================================================ 1. TABLEAU DE BORD
with tabs[0]:
    st.subheader("Tableau de bord")
    bal, eq = float(account["balance"]), float(account["equity"])
    c = st.columns(5)
    c[0].metric("Capital de référence", eur(float(cfg.get("capital", "capital_initial"))))
    c[1].metric("Balance", eur(bal))
    c[2].metric("Equity", eur(eq))
    c[3].metric("P&L latent", eur(eq - bal))
    dd = (state.peak_equity - eq) / state.peak_equity * 100 if state.peak_equity else 0
    c[4].metric("Drawdown", f"{dd:.2f} %")
    c = st.columns(5)
    positions = source.client.positions() if source.live else []
    c[0].metric("Trades ouverts", len(positions))
    orders = storage.read("orders", 500)
    today = now.date().isoformat()
    c[1].metric("Trades du jour", int((orders["ts"].str[:10] == today).sum()) if not orders.empty else 0)
    c[2].metric("Risque par trade", f"{cfg.risk['risque_par_trade_pct']} %")
    c[3].metric("Perte max / jour", f"{cfg.risk['perte_max_jour_pct']} %")
    statut = "⛔ ARRÊTÉ" if kill_switch_active() else ("🟢 ACTIF" if source.live else "🟡 SIMULATION")
    c[4].metric("Statut", statut)

    st.markdown("#### Synthèse des instruments actifs")
    rows = []
    for sym in cfg.active_symbols:
        try:
            a = analyze(cfg, source, sym, calendar, state, now)
            rows.append({"Instrument": sym, "Tendance": a.signal.trend, "Volatilité": a.regime.volatility,
                         "Spread (pts)": a.spread_points, "Signal": a.signal.direction or "—",
                         "Score conditions": f"{a.signal.score:.0%}", "Décision": a.decision,
                         "Raison principale": (a.no_trade_reasons() or [""])[0]})
        except Exception as e:
            rows.append({"Instrument": sym, "Décision": "ERREUR", "Raison principale": str(e)})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.info(f"Calendrier économique : {calendar.message}")

# ================================================================ 2. ANALYSE EN DIRECT
with tabs[1]:
    sym = st.selectbox("Instrument", cfg.active_symbols or ["XAUUSD"], key="live_sym")
    a = analyze(cfg, source, sym, calendar, state, now)
    left, right = st.columns([2.2, 1])
    with left:
        st.plotly_chart(price_chart(a.data, a.levels, a.signal, title=f"{sym} · {a.timeframe}"),
                        width="stretch")
    with right:
        st.markdown(f"### {a.decision}")
        st.markdown(f"**Stratégie :** {a.signal.strategy}")
        st.markdown(f"**Tendance :** {a.signal.trend}  \n**Volatilité :** {a.regime.volatility} "
                    f"(ATR au percentile {a.regime.atr_pct_rank:.0f})  \n**Spread :** {a.spread_points:.0f} points")
        st.markdown(f"**Score statistique (conditions remplies) :** {a.signal.score:.0%}")
        st.caption("Le score mesure la part des conditions remplies, ce n'est PAS une probabilité de gain.")
        if a.signal.confirmations:
            st.markdown("**✅ Ce qui confirme :**\n" + "\n".join(f"- {x}" for x in a.signal.confirmations))
        if a.signal.invalidation:
            st.markdown(f"**Invalidation :** {a.signal.invalidation}")
        p = a.plan
        if p is not None:
            st.markdown("**Plan de trade calculé**")
            st.table(pd.DataFrame({"Valeur": {
                "Direction": p.direction, "Lots": f"{p.lots:.2f}", "Entrée": f"{p.entry:.{a.spec.digits}f}",
                "Stop loss": f"{p.stop_loss:.{a.spec.digits}f}", "Take profit": f"{p.take_profit:.{a.spec.digits}f}",
                "Risque (€)": eur(p.risk_eur), "Risque (% capital)": f"{p.risk_pct:.2f} %",
                "Gain potentiel net": eur(p.profit_potential_eur),
                "R/R nominal / net": f"{p.rr_nominal:.2f} / {p.rr_net:.2f}",
                "Spread estimé": eur(p.spread_cost_eur), "Commission": eur(p.commission_eur),
                "Valeur du pip": eur(p.pip_value_eur), "Marge requise": eur(p.margin_eur),
                "Liquidation (sans SL) à": f"{p.liquidation_distance:.{a.spec.digits}f} de distance"}}))
            for n in p.notes:
                st.warning(n)
        reasons = a.no_trade_reasons()
        if reasons:
            st.markdown("**❌ Pourquoi le robot ne trade pas / pourrait refuser :**\n" + "\n".join(f"- {x}" for x in reasons))
        ev = a.next_event
        st.markdown("**Prochaine annonce :** " + (f"{ev['heure_utc']:%d/%m %H:%M} UTC · {ev['devise']} · {ev['impact']} · "
                                                  f"{ev['evenement']}" if ev else "aucune connue (voir calendrier)"))
        if mode == Mode.ASSISTANCE and a.tradable and source.live:
            st.divider()
            if st.button(f"✅ Valider manuellement l'ordre {p.direction} {p.lots} {sym}", type="primary"):
                from chronyx.execution.executor import OrderRefused, client_order_id, send_market_order
                is_demo = source.is_demo()
                strategies_on_ = [n for n, s in (cfg.get("strategies") or {}).items() if s.get("actif")]
                gate = order_gate(Mode.DEMO_AUTO if is_demo else Mode.REEL, is_demo,
                                  bool(cfg.get("reel", "active", default=False)),
                                  risk_fingerprint(account.get("login"), cfg.risk, strategies_on_))
                try:
                    send_market_order(p, source.client, storage, client_order_id(sym, a.signal.strategy, a.bar_time),
                                      gate, manual_validation=True)
                    st.success("Ordre envoyé avec SL et TP côté broker.")
                except OrderRefused as e:
                    st.error(str(e))

# ================================================================ 3. CAPITAL & FAISABILITÉ
with tabs[2]:
    st.subheader("Le scalping est-il viable avec votre capital ?")
    c1, c2, c3 = st.columns(3)
    capital = c1.slider("Capital (€)", 100, 500, int(min(500, max(100, float(cfg.get("capital", "capital_initial"))))), 10)
    risk_lim = c2.select_slider("Risque max par trade (%)", [0.25, 0.5, 1.0, 2.0], value=float(cfg.risk["risque_par_trade_pct"]))
    comm = c3.number_input("Commission aller-retour (€/lot)", 0.0, 20.0,
                           float(cfg.get("broker", "commission_par_lot_aller_retour", default=0.0)), 0.5)
    rows = []
    symbols = list((cfg.get("instruments") or {}).keys())
    for sym in symbols:
        try:
            spec = source.spec(sym)
            for tf in ("M1", "M5", "M15"):
                d = source.rates(sym, tf)
                from chronyx.analysis.indicators import atr as _atr
                atr_v = float(_atr(d, 14).iloc[-200:].median())
                margin_live = source.client.margin_for(sym, spec.volume_min, True) if source.live else None
                f = assess(spec, tf, capital, atr_v, source.spread_points(sym), comm, risk_lim,
                           float(cfg.risk["stop_loss_atr_mult"]), price=float(d["close"].iloc[-1]),
                           max_margin_pct=float(cfg.risk.get("marge_max_pct_capital", 50)),
                           margin_min_lot_eur=margin_live)
                rows.append({"Instrument": sym, "TF": tf, "Stop typique": round(f.typical_sl_distance, spec.digits),
                             "Risque au lot min (€)": round(f.min_lot_risk_eur, 2),
                             "Risque au lot min (%)": round(f.min_lot_risk_pct, 2),
                             "Frais / stop (%)": round(f.cost_pct_of_stop, 1),
                             "Marge lot min (€)": round(f.min_lot_margin_eur, 0), "Verdict": f.verdict,
                             "Recommandation": f.recommendations[0]})
        except Exception as e:
            rows.append({"Instrument": sym, "Verdict": "erreur", "Recommandation": str(e)})
    fdf = pd.DataFrame(rows)
    st.dataframe(fdf, width="stretch", hide_index=True)
    st.caption(("Spécifications INDICATIVES (mode simulation). " if not source.live else "Spécifications lues dans MT5. ")
               + "Le stop typique = ATR(14) médian x multiplicateur du stop.")
    ok = fdf[fdf.get("Verdict", pd.Series(dtype=str)) == "viable"] if not fdf.empty else fdf
    if ok.empty:
        st.error("Aucune combinaison instrument/timeframe n'est viable avec ces paramètres. "
                 "Recommandation : rester en compte DÉMO, comparer les brokers, ou attendre un capital plus élevé.")
    else:
        st.success("Combinaisons viables : " + ", ".join(f"{r.Instrument} {r.TF}" for r in ok.itertuples()))
    st.info("Avec 100 à 500 €, la marge exigée et le lot minimum (0,01) limitent fortement le scalping de l'or : "
            "le robot refusera tout trade dont le risque minimum dépasse votre limite.")

# ================================================================ 4. BACKTEST
with tabs[3]:
    st.subheader("Backtest")
    c = st.columns(4)
    bt_sym = c[0].selectbox("Instrument", symbols, key="bt_sym")
    bt_strat = c[1].selectbox("Stratégie", list(IMPLEMENTED), format_func=lambda n: IMPLEMENTED[n].label)
    bt_cap = c[2].number_input("Capital initial (€)", 100.0, 100000.0, float(cfg.get("capital", "capital_initial")), 50.0)
    bt_risk = c[3].number_input("Risque/trade (%)", 0.1, 2.0, float(cfg.risk["risque_par_trade_pct"]), 0.25)
    c = st.columns(4)
    bt_rr = c[0].number_input("Risk/Reward", 0.5, 5.0, float(cfg.risk["risk_reward"]), 0.5)
    bt_comm = c[1].number_input("Commission A/R (€/lot)", 0.0, 20.0, float(cfg.get("broker", "commission_par_lot_aller_retour", default=0.0)))
    bt_slip = c[2].number_input("Slippage (points)", 0.0, 50.0, float(cfg.get("backtest", "slippage_points", default=2)))
    bt_periods = c[3].number_input("Périodes de validation", 2, 10, 4)
    if st.button("▶ Lancer le backtest", type="primary"):
        tf = cfg.get("timeframes", "principal", default="M5")
        sp = cfg.get("strategies", bt_strat, default={}) or {}
        strat = build(bt_strat, sp, float(cfg.risk["stop_loss_atr_mult"]), tf)
        d = source.rates(bt_sym, tf)
        prepared = strat.prepare(d, source.rates(bt_sym, sp.get("timeframe_confirmation", "H1")))
        blocked = news_mask(prepared["time"], calendar.events, bt_sym, int(cal_cfg.get("minutes_avant", 15)),
                            int(cal_cfg.get("minutes_apres", 15)))
        bcfg = BacktestConfig(initial_balance=bt_cap, risk_pct=bt_risk, rr=bt_rr, commission_per_lot_rt=bt_comm,
                              slippage_points=bt_slip, break_even_r=float(cfg.risk.get("break_even_r", 0)),
                              max_spread_pct_of_stop=float(cfg.risk.get("spread_max_pct_du_stop", 15)),
                              max_margin_pct=float(cfg.risk.get("marge_max_pct_capital", 50)))
        spec = source.spec(bt_sym)
        res = run_backtest(prepared, spec, bcfg, blocked, IMPLEMENTED[bt_strat].label)
        periods = run_periods(prepared, spec, bcfg, int(bt_periods), blocked, IMPLEMENTED[bt_strat].label)
        rob = robustness_score([r.metrics for r in periods], simulated=res.simulated_data)
        if res.simulated_data:
            st.error("⚠️ DONNÉES SIMULÉES : ces résultats testent le logiciel, ils ne disent RIEN de la rentabilité réelle.")
        m = res.metrics
        k = st.columns(6)
        k[0].metric("Profit net", eur(m["profit_net"]), f"{m['profit_net_pct']:.1f} %")
        k[1].metric("Trades", m["trades"])
        k[2].metric("Win rate", f"{m['win_rate']:.1f} %")
        k[3].metric("Profit factor", f"{m['profit_factor']:.2f}")
        k[4].metric("Drawdown max", f"{m['max_drawdown_pct']:.1f} %")
        k[5].metric("Sharpe", f"{m['sharpe']:.2f}")
        k = st.columns(5)
        k[0].metric("Expectancy", eur(m["expectancy"]), f"{m['expectancy_r']:.2f} R")
        k[1].metric("Gain moyen", eur(m["gain_moyen"]))
        k[2].metric("Perte moyenne", eur(m["perte_moyenne"]))
        k[3].metric("Recovery factor", f"{m['recovery_factor']:.2f}")
        k[4].metric("Trades refusés (risque)", res.refused)
        labels = {"lot_min": "risque au lot minimum trop élevé", "marge": "marge insuffisante",
                  "spread": "spread trop large / stop", "stops": "stop trop proche (broker)"}
        if res.refusal_reasons:
            st.caption("Refus : " + ", ".join(f"{labels.get(k, k)} × {v}" for k, v in res.refusal_reasons.items()))
        if m["trades"] == 0 and res.refused:
            st.error(f"Aucun trade possible : les {res.refused} signaux ont tous été refusés par la gestion du risque. "
                     f"Avec ce capital et ce niveau de risque, {bt_sym} n'est pas tradable avec cette stratégie.")
        st.plotly_chart(equity_chart(res.equity), width="stretch")
        st.markdown(f"#### Robustesse : {rob['verdict']} (score {rob['score']})")
        st.dataframe(pd.DataFrame([{"Période": i + 1, **{k: round(v, 2) if isinstance(v, float) else v
                                                          for k, v in r.metrics.items()}}
                                   for i, r in enumerate(periods)]), width="stretch", hide_index=True)
        if not res.trades.empty:
            st.plotly_chart(price_chart(prepared, {}, None, res.trades, f"{bt_sym} - entrées/sorties (250 dernières bougies)"),
                            width="stretch")
            st.dataframe(res.trades.tail(200), width="stretch", hide_index=True)

# ================================================================ 5. BROKERS
with tabs[4]:
    st.subheader("Comparaison des brokers (aucune sélection automatique)")
    st.warning("Ces données sont à vérifier sur les sources officielles avant toute décision. "
               "CHRONYX n'ouvre aucun compte et ne dépose aucun fonds.")
    st.dataframe(comparison_table(), width="stretch", hide_index=True)
    bdata = load_brokers()
    st.markdown("**Règles UE pour les particuliers :** levier max 1:30 (majeures) / 1:20 (or), protection contre le "
                "solde négatif, clôture à 50 % de marge.")
    st.markdown("**Sources officielles :**\n" + "\n".join(f"- [{s['nom']}]({s['url']})" for s in bdata["sources_officielles"]))
    if source.live:
        if st.button("📏 Mesurer les spreads réels sur le compte connecté (30 s)"):
            from chronyx.brokers.comparison import measure_spreads
            ms = measure_spreads(source.client, cfg.active_symbols, samples=30)
            st.dataframe(pd.DataFrame([m.__dict__ for m in ms]), hide_index=True)
            storage.log_event("INFO", "brokers", f"Spreads mesurés sur {source.name}", {m.symbol: m.median_points for m in ms})
    else:
        st.caption("Connectez un compte démo MT5 pour mesurer les spreads réels de chaque broker.")

# ================================================================ 6. STRATÉGIES
with tabs[5]:
    st.subheader("Bibliothèque de stratégies")
    st.table(pd.DataFrame([{"Stratégie": c.label, "Statut": "Implémentée - à valider par backtest/démo",
                            "Description": c.description} for c in IMPLEMENTED.values()] +
                          [{"Stratégie": v, "Statut": "Prévue (phase 9)", "Description": "Non développée"}
                           for v in PLANNED.values()]))
    st.caption("Aucune stratégie n'est considérée comme rentable avant d'avoir été testée sur des données réelles.")

# ================================================================ 7. PARAMÈTRES
with tabs[6]:
    st.subheader("Paramètres du robot")
    raw = cfg.raw
    r = raw["risque"]
    st.info(f"Recommandation prudente pour {eur(float(raw['capital']['capital_initial']))} : 0,5 % de risque par trade, "
            "1 position à la fois, perte max 2 %/jour. Ne pas dépasser 1 %.")
    with st.form("params"):
        c = st.columns(3)
        presets = {"0,25 %": 0.25, "0,5 %": 0.5, "1 %": 1.0, "2 %": 2.0}
        cur = float(r["risque_par_trade_pct"])
        choice = c[0].selectbox("Risque par trade", list(presets) + ["Personnalisé"],
                                index=list(presets.values()).index(cur) if cur in presets.values() else 4)
        custom = c[0].number_input("Risque personnalisé (%)", 0.05, 2.0, cur, 0.05)
        rr_presets = {"1:1": 1.0, "1:1,5": 1.5, "1:2": 2.0, "1:3": 3.0}
        cur_rr = float(r["risk_reward"])
        rr_choice = c[1].selectbox("Risk/Reward", list(rr_presets) + ["Personnalisé"],
                                   index=list(rr_presets.values()).index(cur_rr) if cur_rr in rr_presets.values() else 4)
        rr_custom = c[1].number_input("R/R personnalisé", 0.5, 10.0, cur_rr, 0.1)
        capital_in = c[2].number_input("Capital de référence (€)", 50.0, 1_000_000.0, float(raw["capital"]["capital_initial"]))
        c = st.columns(4)
        sl_mult = c[0].number_input("Stop loss (x ATR)", 0.5, 5.0, float(r["stop_loss_atr_mult"]), 0.1)
        be = c[1].number_input("Break-even à (R, 0=off)", 0.0, 3.0, float(r["break_even_r"]), 0.5)
        trail = c[2].number_input("Trailing stop (x ATR, 0=off)", 0.0, 5.0, float(r["trailing_stop_atr_mult"]), 0.5)
        max_trades = c[3].number_input("Trades max / jour", 1, 50, int(r["trades_max_par_jour"]))
        c = st.columns(4)
        dl = c[0].number_input("Perte max / jour (%)", 0.5, 5.0, float(r["perte_max_jour_pct"]), 0.5)
        wl = c[1].number_input("Perte max / semaine (%)", 1.0, 15.0, float(r["perte_max_semaine_pct"]), 0.5)
        ddm = c[2].number_input("Drawdown max (%)", 2.0, 20.0, float(r["drawdown_max_pct"]), 1.0)
        npos = c[3].number_input("Positions simultanées", 1, 5, int(r["positions_simultanees_max"]))
        c = st.columns(3)
        pause = c[0].number_input("Pause après perte (min)", 0, 1440, int(r["pause_apres_perte_min"]))
        spread_xau = c[1].number_input("Spread max XAUUSD (pts)", 1, 200, int(r["spread_max_points"].get("XAUUSD", 35)))
        spread_def = c[2].number_input("Spread max autres (pts)", 1, 200, int(r["spread_max_points"].get("defaut", 20)))
        st.markdown("**Instruments actifs**")
        cols = st.columns(5)
        inst = {s: cols[i % 5].checkbox(s, bool(v.get("actif"))) for i, (s, v) in enumerate(raw["instruments"].items())}
        new_mode = st.selectbox("Mode", ["analyse", "assistance", "demo_auto"],
                                index=["analyse", "assistance", "demo_auto"].index(raw["general"]["mode"])
                                if raw["general"]["mode"] in ("analyse", "assistance", "demo_auto") else 0,
                                help="Le mode RÉEL s'active uniquement dans la section dédiée ci-dessous.")
        st.caption("Martingale, grid et récupération des pertes : interdits (non configurables).")
        if st.form_submit_button("💾 Enregistrer", type="primary"):
            r.update(risque_par_trade_pct=presets.get(choice, custom), risk_reward=rr_presets.get(rr_choice, rr_custom),
                     stop_loss_atr_mult=sl_mult, break_even_r=be, trailing_stop_atr_mult=trail,
                     trades_max_par_jour=int(max_trades), perte_max_jour_pct=dl, perte_max_semaine_pct=wl,
                     drawdown_max_pct=ddm, positions_simultanees_max=int(npos), pause_apres_perte_min=int(pause))
            r["spread_max_points"].update(XAUUSD=int(spread_xau), defaut=int(spread_def))
            raw["capital"]["capital_initial"] = capital_in
            for s, v in inst.items():
                raw["instruments"][s]["actif"] = v
            raw["general"]["mode"] = new_mode
            try:
                validated, warns = validate(raw)
                cfg.raw = validated
                cfg.save()
                revoke_real_confirmation()  # toute modification invalide une éventuelle confirmation du réel
                storage.log_event("INFO", "config", "Paramètres modifiés depuis le dashboard")
                st.success("Paramètres enregistrés. Redémarrez le moteur pour les appliquer." + (" " + " ".join(warns) if warns else ""))
            except ValueError as e:
                st.error(str(e))

    st.divider()
    st.markdown("### 🔴 MODE 4 - TRADING RÉEL")
    st.error("Le trading réel est désactivé par défaut. Il peut entraîner la perte de tout le capital déposé.")
    strategies_on = [n for n, s in (cfg.get("strategies") or {}).items() if s.get("actif")]
    st.table(pd.DataFrame({"Valeur": {
        "Capital (balance)": eur(float(account["balance"])), "Broker / serveur": str(account.get("server")),
        "Type de compte": {True: "DÉMO", False: "RÉEL", None: "inconnu"}[source.is_demo()],
        "Risque par trade": f"{r['risque_par_trade_pct']} % ≈ {eur(float(account['balance']) * r['risque_par_trade_pct'] / 100)}",
        "Risque quotidien max": f"{r['perte_max_jour_pct']} % ≈ {eur(float(account['balance']) * r['perte_max_jour_pct'] / 100)}",
        "Perte max semaine / drawdown": f"{r['perte_max_semaine_pct']} % / {r['drawdown_max_pct']} %",
        "Stratégies actives": ", ".join(strategies_on) or "aucune"}}))
    if not cfg.get("reel", "active", default=False):
        st.markdown("Pré-requis : passer `reel: active: true` dans **config.yaml** (édition manuelle volontaire), "
                    "puis revenir ici.")
    elif source.live and source.is_demo() is False:
        phrase = st.text_input(f"Pour confirmer, tapez exactement : {CONFIRMATION_PHRASE}")
        if st.button("Confirmer l'activation du réel (valable 24 h)"):
            fp = risk_fingerprint(account.get("login"), cfg.risk, strategies_on)
            if write_real_confirmation(phrase, fp):
                cfg.raw["general"]["mode"] = "reel"
                cfg.save()
                storage.log_event("CRITICAL", "reel", "Trading réel confirmé manuellement")
                st.success("Confirmation enregistrée. Redémarrez le moteur.")
            else:
                st.error("Phrase incorrecte : activation refusée.")
    else:
        st.caption("Connectez un compte RÉEL dans MetaTrader 5 pour accéder à la confirmation.")
    if st.button("Révoquer immédiatement le mode réel"):
        revoke_real_confirmation()
        cfg.raw["general"]["mode"] = "analyse"
        cfg.save()
        storage.log_event("WARNING", "reel", "Mode réel révoqué")
        st.success("Mode réel révoqué, retour au mode ANALYSE.")

# ================================================================ 8. JOURNAL
with tabs[7]:
    st.subheader("Journal")
    which = st.radio("Table", ["events", "signals", "orders"], horizontal=True,
                     format_func={"events": "Événements", "signals": "Signaux", "orders": "Ordres"}.get)
    st.dataframe(storage.read(which, 500), width="stretch", hide_index=True)
