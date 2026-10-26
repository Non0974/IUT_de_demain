# CampusTwin — jumeau 3D de l'IUT et de la salle

L'interface de suivi des classes est dans [suivi](suivi) (servie par le serveur à l'adresse `/suivi/`) : tableau de bord, séances, classes, fiches des étudiants, Anticipation (prévisions, ventilation, changements de salle) et Assistant IA. Ce dossier contient aussi le jumeau 3D, en deux pages :
- **`iut.html` : tout l'IUT de Sarcelles**, pour le directeur des études. On voit quelle salle est occupée, par quel cours et quel groupe, avec quel enseignant, combien de personnes, qui a badgé et la qualité de l'air.
- **`index.html` : la salle SAR 200 en détail** (la salle équipée de capteurs à la porte), avec le diagnostic de l'air et l'émargement vérifié.

## Vue de tout l'IUT (`iut.html`)

- Les 10 salles et leurs places viennent des emplois du temps CELCAT (GEIIS BUT FI S4, semaine 11, 2025-2026) : SAR 100, 101, 109, 118, 122 au 1er étage, SAR 200, 201, 202, 206, 207 au 2e.
- Les cours des groupes TP1 et TP2 de cette semaine sont **réels** (étiquette « EDT réel »). Les autres cours sont simulés pour remplir les salles.
- **Le plan est schématique** : on n'a pas le vrai plan. Pour le corriger, on modifie l'ordre et le côté des salles dans `js/iut/batiment.js` (le plan d'évacuation du couloir suffit).
- Le nombre de personnes vient des capteurs de la porte en SAR 200, et du Wi-Fi ailleurs (±2 personnes, comme mesuré sur les données ROBOD, voir `../donnees_reelles`).
- L'émargement se fait par badge dans chaque salle. Le directeur voit les présents, les retards et les absents de chaque cours, pas les déplacements d'un étudiant dans le bâtiment (RGPD).
- Les effectifs (9 par groupe), la ventilation des salles et le CO₂ sont inventés pour la démo : un bandeau le rappelle en haut de la page.

| Fichier | Rôle |
| --- | --- |
| `donnees/salles.json` | Les salles (places, surface, étage) : lu aussi par le serveur |
| `donnees/edt.json` | Emploi du temps de la semaine 11, cours réels et simulés : lu aussi par le serveur |
| `js/iut/batiment.js` | Disposition des salles sur le plan |
| `js/iut/edt.js` | Lecture de l'emploi du temps |
| `js/iut/simulationIut.js` | Qui vient, quand, badges, Wi-Fi, CO₂ de chaque salle |
| `js/iut/vueIut.js` | Plan 3D des étages |
| `js/iut/panneauIut.js` | Tableau « qui est où », recherche, détail d'une salle |
| `js/iut/mainIut.js` | Boucle principale |

## Salle SAR 200 en détail (`index.html`)

Salle de cours en 3D dans le navigateur. Elle affiche les étudiants, le CO₂, la ventilation et le diagnostic des quatre causes : ventilation en panne, fenêtre ouverte, capteur de CO₂ qui dérive, comptage faux.

Elle fait aussi l'émargement : chaque étudiant badge sa carte (NFC) à la porte, et chaque badge est comparé aux passages vus par les capteurs de la porte. Une entrée sans badge ou une carte badgée pour un absent est repérée.

Pour l'instant, les capteurs sont **simulés** (`js/simulation.js`). Quand le matériel arrivera, on remplacera la simulation par les vraies mesures.

## Lancer

Le plus simple : double-cliquer sur `lancer.bat` à la racine du projet. Il lance le serveur en simulation et ouvre la page.

Les pages marchent de deux façons :
- **servies par le serveur CampusTwin** (`python serveur/serveur.py`) : elles affichent les données du serveur, capteurs réels ou bâtiment simulé par le serveur. Le temps est celui du serveur ;
- **servies par un simple serveur web** (`python -m http.server 8001` dans ce dossier) : elles simulent elles-mêmes le bâtiment dans le navigateur, avec les boutons de jour et de vitesse.

En ouvrant directement `index.html` (double-clic), le navigateur bloque les modules JavaScript : il faut passer par l'un des deux serveurs. La bibliothèque 3D (Three.js 0.160) est chargée depuis internet.

## Utilisation

- Faire tourner la salle à la souris (clic gauche), zoomer avec la molette.
- **Provoquer une panne** : les boutons du bas déclenchent chaque panne. Le panneau « Diagnostic » montre comment elle est repérée.
- La vitesse règle le temps simulé : × 300 = 5 min par seconde.
- La dérive du capteur de CO₂ est vérifiée la nuit (19 h 30 – 20 h 30). Il faut donc laisser tourner jusqu'au soir.
- **Tester l'émargement** : « Badger aussi la carte d'un absent » et « Entrer sans badger » provoquent une fraude à chaque cours tant que le bouton est rouge. Le panneau « Émargement » montre qui est présent, ce qui est à vérifier, et le lecteur de badge clignote en rouge dans la 3D.
- Le bouton « Télécharger la feuille du jour » donne un CSV (ouvrable dans Excel) avec la présence par cours et par demi-journée.

## Émargement et RGPD

- Les étudiants sont pseudonymisés : le système ne garde qu'une empreinte (hash) du numéro de la carte, pas le nom. Le lien empreinte → nom reste chez la scolarité.
- Pas de caméra : on sait qu'une personne est entrée sans badger, pas qui. C'est l'enseignant qui vérifie.
- Pour les essais, on utilise nos propres cartes ou des cartes de test, et on demande l'avis du DPO de l'université avant de l'utiliser avec une vraie promo.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `js/simulation.js` | Salle simulée : emploi du temps, bilan de CO₂, ventilation, pannes, bruit des capteurs |
| `js/emargement.js` | Badges simulés, appariement badge / passage (10 s), alertes, feuille CSV |
| `js/estimateur.js` | Débit d'air réel calculé de deux façons (avec le comptage, et par la décroissance quand la salle se vide), mesure de nuit, diagnostic des 4 causes, recalage du capteur |
| `js/scene.js` | Scène 3D (Three.js) : salle, tables, étudiants, porte et capteurs, fenêtre, ventilateur, couleur de l'air, flux d'air |
| `js/hud.js` | Panneaux, boutons, courbe du CO₂ |
| `js/main.js` | Boucle principale |

## Prochaines étapes

1. Récupérer le vrai plan des étages (plan d'évacuation) et corriger `js/iut/batiment.js`.
2. Lire l'emploi du temps directement depuis CELCAT (export iCal) au lieu de le recopier.
3. Demander à la DSI le nombre d'appareils connectés par borne Wi-Fi.
