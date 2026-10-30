# Total Buts

Appli de téléphone qui estime chaque jour la probabilité de **plus de 1,5 / 2 / 2,5 buts** dans les matchs de 10 championnats européens, et propose des coupons classés par priorité.

Tout tourne gratuitement sur GitHub : un calcul automatique toutes les heures met à jour l'appli publiée sur GitHub Pages.

## Ce que fait le calcul

1. **Données** : résultats et cotes de [football-data.co.uk](https://www.football-data.co.uk) (8 saisons d'historique, matchs à venir avec cotes).
2. **Modèle** : Dixon-Coles pondéré dans le temps (forces d'attaque et de défense par équipe, avantage du terrain, correction des petits scores), mélangé avec la probabilité implicite du marché. Le poids du mélange est choisi chaque semaine par le test sur le passé.
3. **Retour d'expérience** : chaque match joué corrige la calibration de sa ligue, et la réussite de nos coupons règle la confiance accordée à chaque championnat.
4. **Coupons** : sûrs (3 à 4 matchs, cote ≥ 2), par championnat, value, audacieux et jackpot, sans nombre fixe par jour, classés par priorité. Chaque sélection donne la cote minimum à exiger chez le bookmaker.
5. **Suivi** : les coupons sont réglés automatiquement avec les scores réels.

## Fichiers

- `pipeline/` : calcul en Python (`run_daily.py` est le point d'entrée).
- `docs/` : l'appli (HTML/JS, installable sur l'écran d'accueil) et ses données (`docs/data/`).
- `data/` : historique téléchargé et mémoire des coupons et prédictions.

Aucun modèle ne garantit des gains. Joue seulement ce que tu peux te permettre de perdre.

## Révision (6e à Terminale)

Deuxième appli, sans lien avec les paris : quiz de révision de la 6e à la Terminale (séries L et S), publiée sur `/revision/`.
Le manifeste de Total Buts a pour portée `index.html` pour que les deux applis s'installent séparément sur le téléphone.
Les questions sont dans `revision/questions.py`, `q_college.py` et `q_lycee.py` ; `python revision/build.py` régénère `docs/revision/data/`.
Les 5 premières questions de chaque matière sont gratuites, le reste se débloque avec un code premium vendu par Wave.
Seuls les hachages des codes sont publiés (`revision/code_hashes.txt`) ; la liste en clair reste hors du dépôt.
