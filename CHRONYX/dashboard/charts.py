"""Graphiques Plotly du dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

GOLD, UP, DOWN, MUTED = "#F5B700", "#26A69A", "#EF5350", "#8A8F98"


def price_chart(d: pd.DataFrame, levels: dict, signal=None, trades: pd.DataFrame | None = None,
                title: str = "", bars: int = 250) -> go.Figure:
    d = d.tail(bars)
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, row_heights=[0.55, 0.15, 0.15, 0.15],
                        vertical_spacing=0.02, subplot_titles=(title, "RSI", "MACD", "ATR"))
    fig.add_trace(go.Candlestick(x=d["time"], open=d["open"], high=d["high"], low=d["low"], close=d["close"],
                                 name="Prix", increasing_line_color=UP, decreasing_line_color=DOWN), 1, 1)
    for col, color, name in (("ema_fast", GOLD, "EMA 20"), ("ema_mid", "#42A5F5", "EMA 50"),
                             ("ema_slow", "#AB47BC", "EMA 200")):
        if col in d:
            fig.add_trace(go.Scatter(x=d["time"], y=d[col], line=dict(color=color, width=1.2), name=name), 1, 1)
    for lvl in levels.get("resistances", []):
        fig.add_hline(y=lvl, line=dict(color=DOWN, width=0.7, dash="dot"), row=1, col=1)
    for lvl in levels.get("supports", []):
        fig.add_hline(y=lvl, line=dict(color=UP, width=0.7, dash="dot"), row=1, col=1)
    if signal is not None and signal.direction:
        fig.add_hline(y=signal.entry, line=dict(color="white", width=1), annotation_text="Entrée", row=1, col=1)
        fig.add_hline(y=signal.stop_loss, line=dict(color=DOWN, width=1.5), annotation_text="SL", row=1, col=1)
        fig.add_hline(y=signal.take_profit, line=dict(color=UP, width=1.5), annotation_text="TP", row=1, col=1)
    if trades is not None and not trades.empty:
        t = trades[trades["entry_time"] >= d["time"].iloc[0]]
        fig.add_trace(go.Scatter(x=t["entry_time"], y=t["entry"], mode="markers", name="Entrées",
                                 marker=dict(symbol="triangle-up", size=9, color=GOLD)), 1, 1)
        fig.add_trace(go.Scatter(x=t["exit_time"], y=t["exit"], mode="markers", name="Sorties",
                                 marker=dict(symbol="x", size=8, color="white")), 1, 1)
    if "rsi" in d:
        fig.add_trace(go.Scatter(x=d["time"], y=d["rsi"], line=dict(color=GOLD, width=1), name="RSI"), 2, 1)
        for y in (30, 70):
            fig.add_hline(y=y, line=dict(color=MUTED, width=0.6, dash="dash"), row=2, col=1)
    if "macd" in d:
        fig.add_trace(go.Bar(x=d["time"], y=d["macd_hist"], marker_color=[UP if v >= 0 else DOWN for v in d["macd_hist"].fillna(0)],
                             name="Histogramme"), 3, 1)
        fig.add_trace(go.Scatter(x=d["time"], y=d["macd"], line=dict(color="#42A5F5", width=1), name="MACD"), 3, 1)
        fig.add_trace(go.Scatter(x=d["time"], y=d["macd_signal"], line=dict(color=GOLD, width=1), name="Signal"), 3, 1)
    if "atr" in d:
        fig.add_trace(go.Scatter(x=d["time"], y=d["atr"], line=dict(color="#AB47BC", width=1), name="ATR"), 4, 1)
    fig.update_layout(template="plotly_dark", height=820, showlegend=False, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="#0E1117", plot_bgcolor="#0E1117")
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig


def equity_chart(equity: pd.DataFrame, title: str = "Courbe de capital") -> go.Figure:
    fig = go.Figure(go.Scatter(x=equity["time"], y=equity["equity"], line=dict(color=GOLD, width=1.6), fill="tozeroy",
                               fillcolor="rgba(245,183,0,0.08)"))
    fig.update_layout(template="plotly_dark", height=320, title=title, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", yaxis_title="€")
    return fig


def _layout(fig: go.Figure, title: str, height: int = 320) -> go.Figure:
    fig.update_layout(template="plotly_dark", height=height, title=title, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", showlegend=False)
    return fig


def cumulative_pnl_chart(trades: pd.DataFrame) -> go.Figure:
    t = trades.sort_values("fermeture")
    cum = t["pnl_eur"].cumsum()
    color = UP if (cum.iloc[-1] if len(cum) else 0) >= 0 else DOWN
    fig = go.Figure(go.Scatter(x=t["fermeture"], y=cum, mode="lines+markers", line=dict(color=color, width=2),
                               marker=dict(size=5, color=[UP if v > 0 else DOWN for v in t["pnl_eur"]]),
                               hovertemplate="%{x|%d/%m %H:%M}<br>Cumul : %{y:.2f} €<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=MUTED, width=0.8))
    return _layout(fig, "Gains / pertes cumulés (€)")


def daily_pnl_chart(daily: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(x=daily["jour"].astype(str), y=daily["pnl_eur"],
                           marker_color=[UP if v >= 0 else DOWN for v in daily["pnl_eur"]],
                           hovertemplate="%{x}<br>%{y:.2f} €<extra></extra>"))
    return _layout(fig, "Résultat par jour (€)")


def instrument_pnl_chart(by_inst: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(y=by_inst["symbole"], x=by_inst["gains"], orientation="h", marker_color=UP, name="Gains"))
    fig.add_trace(go.Bar(y=by_inst["symbole"], x=by_inst["pertes"], orientation="h", marker_color=DOWN, name="Pertes"))
    fig.add_trace(go.Scatter(y=by_inst["symbole"], x=by_inst["pnl_eur"], mode="markers", name="Net",
                             marker=dict(color="white", size=10, symbol="diamond")))
    fig.update_layout(barmode="relative")
    return _layout(fig, "Gains et pertes par instrument (€) — ◆ = net", height=max(220, 70 * len(by_inst) + 80))
