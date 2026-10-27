# CampusTwin : site et jumeau 3D

Le site de suivi des classes est dans [suivi](suivi), à l'adresse `/suivi/` du serveur : tableau de bord, séances, classes, fiches des étudiants, Anticipation, Tickets et Assistant IA.

Ce dossier contient aussi le jumeau 3D, en deux pages. `iut.html` montre tout l'IUT de Sarcelles pour le directeur des études : quelle salle est occupée, par quel cours, avec quel enseignant, combien de personnes, qui a badgé et l'air. `index.html` montre la salle SAR 200 en détail (celle qui a les capteurs à la porte), avec le diagnostic de l'air et l'émargement.

## Vue de tout l'IUT (`iut.html`)

Les 23 salles et leurs places viennent des emplois du temps CELCAT (2025-2026 et 2026-2027) : 2 amphis (80 et 120 places) et 2 salles au rez-de-chaussée, 9 salles au 1er étage et 10 au 2e. L'étage est déduit du numéro de la salle. Les cours de notre classe, BUT3 ESE FA S5 (TD1 = TP1 + TP2), pour la semaine du 16 novembre 2026, sont les vrais cours lus dans CELCAT. Les autres cours sont simulés pour remplir les salles.

On n'a pas le vrai plan du bâtiment, donc le plan est schématique. Pour le corriger, il suffit de changer l'ordre et le côté des salles dans `js/iut/batiment.js` (le plan d'évacuation du couloir suffit).

Le nombre de personnes vient des capteurs de la porte en SAR 200, et du Wi-Fi ailleurs (à 2 personnes près, d'après les données ROBOD, voir `../donnees_reelles`). L'émargement se fait par badge dans chaque salle. Le directeur voit les présents, les retards et les absents de chaque cours, mais pas les déplacements d'un étudiant dans le bâtiment.

Les effectifs (9 par demi-groupe, à confirmer), la ventilation des salles et le CO₂ sont inventés pour la démo. Un bandeau le rappelle en haut de la page.

| Fichier | Rôle |
| --- | --- |
| `donnees/salles.json` | Les salles (places, surface, étage), lu aussi par le serveur |
| `donnees/edt.json` | Emploi du temps de la semaine du 16 novembre 2026, lu aussi par le serveur |
| `js/iut/batiment.js` | Disposition des salles sur le plan |
| `js/iut/edt.js` | Lecture de l'emploi du temps |
| `js/iut/simulationIut.js` | Qui vient, quand, badges, Wi-Fi, CO₂ de chaque salle |
| `js/iut/vueIut.js` | Plan 3D des étages |
| `js/iut/panneauIut.js` | Tableau « qui est où », recherche, détail d'une salle |
| `js/iut/mainIut.js` | Boucle principale |

## Salle SAR 200 en détail (`index.html`)

C'est une salle de cours en 3D dans le navigateur. On voit les étudiants, le CO₂, la ventilation et le diagnostic (ventilation en panne, fenêtre ouverte, capteur qui dérive, comptage faux). L'émargement se fait aussi : chaque étudiant badge sa carte à la porte, et le badge est comparé aux passages vus par les capteurs, ce qui permet de voir une entrée sans badge ou une carte badgée pour un absent.

Pour l'instant les capteurs sont simulés (`js/simulation.js`). Quand le matériel arrivera, on branchera les vraies mesures.

## Lancer

Le plus simple est de double-cliquer sur `lancer.bat` à la racine du projet : il lance le serveur en simulation et ouvre la page.

Avec le serveur CampusTwin (`python serveur/serveur.py`), les pages affichent les données du serveur. Avec un simple serveur web (`python -m http.server 8001` dans ce dossier), elles simulent le bâtiment dans le navigateur, avec des boutons pour le jour et la vitesse. Si on ouvre `index.html` directement par double-clic, le navigateur bloque les modules JavaScript. La bibliothèque 3D (Three.js 0.160) est chargée depuis internet.

## Utilisation

On fait tourner la salle avec le clic gauche et on zoome avec la molette. Les boutons du bas provoquent les pannes, et le panneau « Diagnostic » montre comment elles sont repérées. La vitesse règle le temps simulé (× 300 = 5 minutes par seconde). La dérive du capteur est vérifiée le soir entre 19 h 30 et 20 h 30, il faut donc laisser tourner jusque-là.

Pour tester l'émargement, les boutons « Badger aussi la carte d'un absent » et « Entrer sans badger » provoquent une fraude à chaque cours tant qu'ils sont rouges. Le bouton « Télécharger la feuille du jour » donne un CSV avec la présence par cours et par demi-journée.

## Émargement et RGPD

Le système ne garde qu'une empreinte du numéro de la carte, pas le nom. Le lien entre l'empreinte et le nom reste chez la scolarité. Il n'y a pas de caméra : on sait qu'une personne est entrée sans badger, mais pas qui, et c'est l'enseignant qui vérifie. Pour les essais, on utilise nos propres cartes ou des cartes de test, et on demandera l'avis du DPO de l'université avant de l'utiliser avec une vraie promo.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `js/simulation.js` | Salle simulée : emploi du temps, CO₂, ventilation, pannes, bruit des capteurs |
| `js/emargement.js` | Badges simulés, lien badge / passage (10 s), alertes, feuille CSV |
| `js/estimateur.js` | Débit d'air calculé de deux façons, mesure du soir, diagnostic, recalage du capteur |
| `js/scene.js` | Scène 3D (Three.js) : salle, tables, étudiants, porte, capteurs, fenêtre, ventilateur |
| `js/hud.js` | Panneaux, boutons, courbe du CO₂ |
| `js/main.js` | Boucle principale |

## Prochaines étapes

1. Récupérer le vrai plan des étages (plan d'évacuation) et corriger `js/iut/batiment.js`.
2. Lire l'emploi du temps de toutes les salles dans CELCAT, pas seulement celui de notre classe.
3. Demander à la DSI le nombre d'appareils connectés par borne Wi-Fi.
