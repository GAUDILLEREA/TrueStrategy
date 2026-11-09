"""Statistiques de performance et classement des stratégies."""
from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    """Renvoie (drawdown max en €, en %)."""
    if equity.empty:
        return 0.0, 0.0
    peak = equity.cummax()
    dd = peak - equity
    i = int(dd.to_numpy().argmax())
    pct = float(dd.iloc[i] / peak.iloc[i] * 100) if peak.iloc[i] > 0 else 0.0
    return float(dd.max()), pct


def compute_metrics(trades: pd.DataFrame, equity: pd.DataFrame, initial_balance: float) -> dict:
    if trades.empty:
        return {"trades": 0, "profit_net": 0.0, "profit_net_pct": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
                "expectancy": 0.0, "expectancy_r": 0.0, "sharpe": 0.0, "max_drawdown": 0.0,
                "max_drawdown_pct": 0.0, "recovery_factor": 0.0, "gain_moyen": 0.0, "perte_moyenne": 0.0,
                "frais_totaux": 0.0}
    pnl = trades["pnl"]
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    net = float(pnl.sum())
    dd, dd_pct = max_drawdown(equity["equity"])

    # Sharpe annualisé sur rendements JOURNALIERS (les jours sans trade comptent comme 0)
    eq = equity.set_index(pd.to_datetime(equity["time"]))["equity"]
    daily = eq.resample("1D").last().dropna()
    daily = daily[daily.index.dayofweek < 5]
    rets = daily.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 2 and rets.std() > 0 else 0.0

    return {
        "trades": int(len(trades)),
        "profit_net": net,
        "profit_net_pct": net / initial_balance * 100,
        "win_rate": float(len(wins) / len(trades) * 100),
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "expectancy": float(pnl.mean()),
        "expectancy_r": float(trades["r_multiple"].mean()),
        "sharpe": sharpe,
        "max_drawdown": dd,
        "max_drawdown_pct": dd_pct,
        "recovery_factor": float(net / dd) if dd > 0 else float("inf") if net > 0 else 0.0,
        "gain_moyen": float(wins.mean()) if len(wins) else 0.0,
        "perte_moyenne": float(losses.mean()) if len(losses) else 0.0,
        "frais_totaux": float(trades["commission"].sum() - trades["swap"].sum()),
    }


def robustness_score(period_metrics: list[dict], min_trades: int = 100, simulated: bool = False) -> dict:
    """Score de robustesse : favorise la RÉGULARITÉ entre périodes, pas le meilleur résultat.

    - pénalise un nombre de trades insuffisant (statistiquement non significatif) ;
    - utilise la pire période et la médiane plutôt que la moyenne ;
    - pénalise le drawdown.
    """
    total = sum(m["trades"] for m in period_metrics)
    pfs = [min(m["profit_factor"], 3.0) for m in period_metrics if m["trades"] > 0]
    positives = sum(1 for m in period_metrics if m["profit_net"] > 0)
    worst_dd = max((m["max_drawdown_pct"] for m in period_metrics), default=0.0)
    if total < min_trades or not pfs:
        return {"score": 0.0, "verdict": f"Échantillon insuffisant ({total} trades < {min_trades}) : non évaluable.",
                "trades": total}
    med_pf, min_pf = float(np.median(pfs)), float(min(pfs))
    consistency = positives / len(period_metrics)
    score = max(0.0, (med_pf - 1) * 40 + (min_pf - 1) * 30 + consistency * 30 - worst_dd)
    if med_pf > 1.2 and min_pf >= 0.95 and consistency >= 0.75:
        verdict = "Prometteur sur l'historique testé : à confirmer en démo."
    elif med_pf > 1.0:
        verdict = "Fragile : résultats irréguliers entre périodes."
    else:
        verdict = "Non rentable sur l'historique testé."
    if simulated:
        verdict = "DONNÉES SIMULÉES : aucune conclusion de rentabilité possible."
    return {"score": round(score, 1), "verdict": verdict, "trades": total, "pf_median": med_pf, "pf_min": min_pf,
            "periodes_positives": f"{positives}/{len(period_metrics)}", "pire_drawdown_pct": worst_dd}
