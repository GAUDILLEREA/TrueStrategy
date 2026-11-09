# Guide utilisateur CHRONYX

## 1. Démarche recommandée (dans cet ordre)

1. **Installation** et diagnostic (`installer.bat`, puis `verifier_environnement.bat`).
2. **Compte démo MT5** connecté, mode **ANALYSE** : observer les signaux et les raisons de refus pendant quelques jours.
3. Onglet **Capital & faisabilité** : vérifier quels instruments sont compatibles avec votre capital.
4. Onglet **Brokers** : ouvrir des comptes **démo** chez 2 ou 3 brokers éligibles et **mesurer leurs spreads réels**.
5. **Backtest** sur les données réelles de votre broker (au moins plusieurs milliers de bougies), vérifier le verdict
   de robustesse.
6. Mode **ASSISTANCE** (démo) : valider manuellement les propositions.
7. Mode **DÉMO AUTOMATIQUE** pendant plusieurs semaines. Comparer les résultats au backtest.
8. Seulement ensuite, et si les résultats sont stables, envisager le réel avec le risque minimum.

## 2. Le dashboard

| Onglet | Contenu |
|---|---|
| 🏠 Tableau de bord | Capital, balance, equity, P&L, drawdown, positions, trades du jour, statut, synthèse par instrument |
| 💼 Positions & résultats | Positions ouvertes (P&L, perte au SL, gain au TP, bouton *Fermer*), gains/pertes par période, courbe cumulée, résultat par jour, instruments tradés, historique exportable en CSV |
| 🛡️ Gestion du risque | Jauges colorées : perte du jour/semaine, drawdown, risque ouvert, positions, trades du jour ; règles actives |
| ⏸️ Pause & retraits | Pause / reprise, fermeture de toutes les positions, procédure de retrait, simulateur de retrait, dépôts et retraits enregistrés |
| 📈 Analyse en direct | Graphique chandeliers + EMA, S/R, SL/TP, RSI, MACD, ATR ; explication complète du signal ; raisons d'absence de trade ; prochaine annonce |
| 💶 Capital & faisabilité | Risque au lot minimum, marge, poids des frais, verdict par instrument et timeframe |
| 🧪 Backtest | Statistiques complètes, courbe de capital, robustesse par période, liste des trades |
| 🏦 Brokers | Tableau comparatif, sources officielles, mesure des spreads réels |
| 📚 Stratégies | Statut de chaque stratégie |
| ⚙️ Paramètres | Risque, R/R, SL, break-even, trailing, limites de pertes, spreads, instruments, mode ; activation du réel |
| 📜 Journal | Événements, signaux, ordres |

**Bouton ⏸️ Pause** (barre latérale et onglet *Pause & retraits*) : le robot n'ouvre plus de position, mais les
positions déjà ouvertes restent ouvertes, protégées par leur SL/TP. Fonctionne aussi dashboard fermé (fichier `data/PAUSE`).

**Retraits** : CHRONYX ne peut pas retirer d'argent (sécurité volontaire). Le retrait se fait dans l'espace client du
broker. Mettez d'abord le robot en pause, laissez les positions se clôturer, retirez, puis reprenez.

**Bouton ⛔ STOP GLOBAL** (barre latérale) : bloque toute nouvelle position ; le moteur ferme les positions ouvertes par CHRONYX.
Il reste actif jusqu'à ce que vous le leviez manuellement.

## 3. Lire un signal

Pour chaque instrument, CHRONYX affiche :
- la **stratégie**, la **tendance**, la **volatilité** ;
- les **conditions remplies** (✅) et **non remplies** ;
- le **score** = part des conditions remplies (ce n'est **pas** une probabilité de gain) ;
- le **plan de trade** : lots, entrée, SL, TP, risque en € et en %, gain potentiel net, R/R après frais, spread,
  commission, valeur du pip, marge, distance de liquidation ;
- les **raisons de refus** (données, calendrier, horaires, spread, limites de pertes, lot minimum, marge…).

## 4. Les paramètres de risque

| Paramètre | Défaut | Conseil pour 100-500 € |
|---|---|---|
| Risque par trade | 0,5 % | 0,25 à 0,5 % ; ne pas dépasser 1 % |
| Risk/Reward | 1:1,5 | ≥ 1:1,5 (les frais réduisent le R/R réel) |
| Stop loss | 1,5 × ATR | Un stop trop serré est mangé par le spread |
| Perte max / jour | 2 % | Arrêt du trading pour la journée |
| Perte max / semaine | 5 % | |
| Drawdown max | 10 % | Déclenche le STOP GLOBAL automatique |
| Positions simultanées | 1 | |
| Pause après perte | 30 min | Évite le « revenge trading » |

## 5. Calendrier économique

- Mis à jour par `maj_calendrier.bat` (et à chaque `start_bot.bat`) depuis le flux hebdomadaire public de Forex Factory
  (source tierce, non officielle).
- Recouper les annonces majeures avec les sources officielles : Fed (FOMC), BLS (NFP, CPI), BEA (PCE, PIB), BCE.
- Par défaut, les trades sont bloqués **15 min avant et 15 min après** une annonce à fort impact sur les devises de
  l'instrument (USD pour l'or). Réglable dans `config.yaml` (`calendrier.minutes_avant / minutes_apres`).
- **Si le calendrier est absent, vide, illisible ou vieux de plus de 24 h : aucun trade.**
- Saisie manuelle possible : `data/calendrier.csv` avec les colonnes `datetime_utc,currency,impact,event`.

## 6. Configuration du broker

Dans `config.yaml` :
- `broker.suffixe_symboles` : suffixe éventuel des symboles (ex. `.r`, `m`) ;
- `broker.commission_par_lot_aller_retour` : commission aller-retour par lot (comptes « Raw/ECN ») ;
- `instruments` : activer/désactiver chaque symbole.

Les spécifications (lot minimum, taille de contrat, valeur du tick, distance minimale des stops, marge) sont **lues
directement dans MetaTrader 5** et donc propres à votre broker.

## 7. Activer le trading réel (déconseillé avant validation complète)

1. Éditer `config.yaml` à la main : `reel: active: true`.
2. Connecter le compte réel dans MT5.
3. Dashboard → Paramètres → section MODE 4 : relire le récapitulatif (capital, broker, risques, stratégies, limites).
4. Taper exactement la phrase de confirmation. Valable 24 h ; annulée par toute modification des paramètres.
5. Redémarrer le moteur. Le bouton « Révoquer immédiatement le mode réel » ramène au mode ANALYSE.
