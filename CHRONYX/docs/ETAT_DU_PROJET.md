# État du projet CHRONYX — v0.1.0

Légende : ✅ fait et couvert par des tests automatiques · 🟡 écrit mais **non testé sur un vrai MetaTrader 5** ·
⏳ à faire.

L'environnement de développement de cette version est Linux, sans MetaTrader 5 (le paquet Python MetaTrader5
n'existe que sous Windows). Tout ce qui touche à la connexion réelle au terminal est donc marqué 🟡 et doit être
validé sur votre PC avec un compte **démo**.

## Architecture

```
CHRONYX/
├── start_bot.bat / installer.bat / *.bat     Lancement et outils Windows
├── config.yaml                               Paramètres (validés, plafonds absolus)
├── verifier_environnement.py                 Diagnostic Windows / Python / MT5
├── chronyx/
│   ├── config.py                             Chargement + garde-fous de configuration
│   ├── secrets.py                            Mots de passe via le Gestionnaire d'identifiants Windows
│   ├── data/        mt5_client, symbol_spec, quality, storage (SQLite), sample_data (simulation)
│   ├── analysis/    indicators (EMA, RSI, ATR, MACD, S/R), regime
│   ├── strategies/  base (signal explicable, fusion multi-TF sans look-ahead), trend_scalping, registry
│   ├── risk/        position_sizing, guards (coupe-circuits), feasibility
│   ├── news/        calendar (filtre fail-closed), importer
│   ├── backtest/    engine, metrics (stats + robustesse)
│   ├── brokers/     brokers.yaml, comparison
│   ├── account/     portfolio (positions, historique, gains/pertes, dépôts/retraits, jauges de risque)
│   ├── execution/   modes (verrou du réel), executor (ordres MT5 avec SL/TP, anti-doublon)
│   └── engine/      sources (MT5 / simulation), pipeline (décision unique), bot (moteur autonome)
├── dashboard/       app.py (Streamlit), account_tabs.py (positions / risque / pause & retraits), charts.py (Plotly)
├── tests/           69 tests pytest
└── docs/
```

Principe clé : **une seule chaîne de décision** (`engine/pipeline.py`) utilisée par le moteur ET le dashboard, pour
que ce qui est affiché soit exactement ce que le robot ferait.

## Phases

| Phase | Contenu | État |
|---|---|---|
| 1 | Architecture, installation Windows, diagnostic | ✅ (scripts .bat à exécuter sur votre PC) |
| 2 | Connexion MT5, données, spécifications broker | 🟡 code écrit ; contrôle qualité ✅ |
| 3 | Analyse technique XAUUSD / Forex | ✅ |
| 4 | Stratégie A — scalping de tendance | ✅ logique testée ; **rentabilité inconnue** |
| 5 | Gestion du risque, calcul des lots, faisabilité | ✅ |
| 6 | Backtesting | ✅ (sur données réelles MT5 : 🟡) |
| 7 | Dashboard | ✅ testé dans Chromium en mode simulation |
| 8 | Calendrier économique | ✅ filtre ; import automatique 🟡 (flux non joignable depuis l'environnement de dev) |
| 9 | Stratégies B (breakout), C (pullback), D (price action), E (gold momentum) ; recherche documentée | ⏳ |
| 10 | Module IA (régimes, sélection de stratégie, validation walk-forward) | ⏳ (régime à règles en place) |
| 11 | Démo automatique | 🟡 exécuteur + verrou écrits, verrou ✅ ; envoi d'ordres à valider en démo |
| 12 | Tests et documentation | ✅ pour la v0.1 |
| + | Écrans Positions & résultats, Gestion du risque, Pause & retraits | ✅ interface testée ; lecture MT5 testée avec un faux MT5 (🟡 à confirmer en démo) |

## Limites connues de la v0.1

- Trailing stop : paramètre présent, **pas encore appliqué** (ni en backtest ni en live). Break-even : appliqué en backtest seulement.
- Backtest sur une seule stratégie et un seul instrument à la fois ; pas encore de classement multi-stratégies.
- Résultats de backtest en mode simulation : **sans valeur** pour juger la rentabilité (affiché en rouge).
- Mode Assistance : validation manuelle depuis l'onglet Analyse ; pas encore de file d'attente de propositions.
- Les données brokers (`brokers.yaml`) sont toutes au statut « à vérifier » : spreads/commissions non renseignés
  tant qu'ils n'ont pas été relevés sur les sources officielles ou mesurés en démo.
- Swap : paramètre global en backtest (à lire par symbole dans MT5 plus tard).
