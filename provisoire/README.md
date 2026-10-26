# IUT_de_demain — CampusTwin (dossier provisoire)

> **Dossier provisoire** : tout le projet est rangé ici pour l'instant. On réorganisera le dépôt en équipe.
> Les commandes ci-dessous se lancent depuis ce dossier `provisoire/`.
> Les noms des enseignants sont remplacés par « Enseignant A, B… » (dépôt public).

Ce projet a pour but de créer l'IUT de demain. À l'aide de nos connaissances acquises au cours de nos deux années en BUT GEII, nous allons réaliser un système qui pourra améliorer notre quotidien au sein de l'établissement.

**CampusTwin : une salle qui sait pourquoi son air est mauvais, et un IUT où l'on sait qui est dans quelle salle.**

SAE BUT 3 GEII, IUT de Cergy-Pontoise, site de Sarcelles. Louay Boubaya, Ariel Guarise-Preller, Noah Poiré.

## Ce que fait le système

- **Compter les personnes sans caméra.** À la porte de la salle SAR 200, trois capteurs votent pour chaque passage : un ToF 8×8, une caméra thermique 32×24 et un radar. Dans les autres salles, le Wi-Fi donne une estimation à ±2 personnes.
- **Trouver pourquoi l'air est mauvais.** Le bilan de CO₂ donne le vrai débit d'air de deux façons : avec le comptage quand la salle est occupée, et sans le comptage quand elle se vide. En les comparant avec la mesure du soir, on sépare 5 causes :
  - ventilation en panne ;
  - fenêtre ouverte ;
  - capteur de CO₂ qui dérive ;
  - comptage faux ;
  - capteur mal placé.
- **Émargement vérifié.** Chaque étudiant badge sa carte (NFC) en entrant, et chaque badge est comparé aux passages comptés. On repère une entrée sans badge ou une carte prêtée. Seule une empreinte de la carte est gardée (RGPD).
- **Interface de suivi des classes**, avec des comptes : directeur des études, scolarité, enseignant.
  - Tableau de bord en direct : séances en cours, présents, absents, alertes.
  - Séances du jour, et feuille d'émargement de chaque séance, imprimable.
  - Une classe sur la semaine : un tableau étudiants × séances, avec le taux de présence.
  - Fiche de chaque étudiant.
  - Un enseignant peut corriger un statut (oubli de badge, absence justifiée) : la correction est gardée avec son nom, l'heure et le motif.
  - Export CSV pour le CFA, avec la présence par demi-journée.
  - Un enseignant ne voit que ses cours et ses classes (RGPD).
  - Anticipation : CO₂ prévu, plan de ventilation, énergie économisée, propositions de salle.
  - Assistant IA : questions en français.
- **Jumeau prédictif.** Le jumeau prévoit le CO₂ de chaque salle pour les 2 prochaines heures, avec l'emploi du temps, le taux de présence et le débit d'air qu'il a appris.
  - Dans SAR 200, il ventile avant que la salle se remplisse et coupe quand personne n'arrive (commande prédictive). Sur une semaine simulée : 17 % d'énergie de ventilation en moins que la règle simple, et 171 minutes au-dessus de 1000 ppm au lieu de 239.
  - Si l'air d'un cours va dépasser 1200 ppm, il propose une salle libre où l'air restera bon. Le directeur accepte ou ignore, dans la page Anticipation.
- **Assistant IA.** On pose une question en français : « Qui est absent en SAR 109 ? », « Quelle salle aura l'air mauvais dans l'heure ? ». Claude (Anthropic) lit les données et répond.
  - Il ne voit aucun nom : les étudiants deviennent ETU-001, ETU-002…, les enseignants « Enseignant A, B… », et les motifs d'absence ne partent pas. Le serveur remet les vrais noms à l'affichage.
  - Il a les droits de la personne connectée et ne modifie rien.
- **Vue 3D du directeur des études.** Le plan 3D de l'IUT montre, pour chaque salle :
  - le cours, le groupe et l'enseignant ;
  - les présents, retards et absents ;
  - l'air.
- **Automate S7-1200.** Il pilote une maquette qui reproduit la ventilation de la salle, avec arrêt d'urgence, mode manuel et repli si le serveur ne répond plus.

## Organisation

| Dossier | Contenu | État |
| --- | --- | --- |
| [jumeau3d/suivi](jumeau3d/suivi) | Interface de suivi des classes (tableau de bord, séances, classes, étudiants, anticipation, assistant IA) | marche, vérifiée dans le navigateur |
| [jumeau3d](jumeau3d) | Jumeau 3D : vue de tout l'IUT (`iut.html`) et salle SAR 200 en détail (`index.html`) | marche, vérifié dans le navigateur |
| [serveur](serveur) | Serveur Python sans installation : capteurs, diagnostic, registre des présences, comptes, prévisions, ventilation anticipée, lien avec l'automate, assistant IA | marche, testé en simulation (assistant : testé avec un faux client, pas encore avec la vraie API) |
| [simulateurs](simulateurs) | Bâtiment simulé (mêmes messages que les vraies cartes) et automate simulé (Modbus TCP) | marche |
| [tests](tests) | Pannes et fraudes sur une semaine simulée, automate, suivi des classes, prévisions, assistant IA | tous les tests passent |
| [firmware](firmware) | Code des cartes XIAO ESP32S3 : nœud salle (CO₂, badge, écran) et nœud porte (fusion des 3 capteurs) | compile, pas encore testé sur le matériel |
| [automate](automate) | Programme SCL du S7-1200 et branchements | écrit, pas encore compilé dans TIA Portal |
| [donnees_reelles](donnees_reelles) | Tests sur des données publiques réelles (ROBOD, salle danoise OU44) et IA du Wi-Fi | fait |
| [docs](docs) | Synthèse du projet et proposition de matériel | |

## Essayer tout de suite (sans matériel)

Il faut Python 3.10 ou plus. Double-cliquer sur `lancer.bat`, ou :

```
python serveur/serveur.py --simulation
```

Puis ouvrir http://localhost:8000 et se connecter avec un compte de démonstration :
- **directeur** / **demo** : voit tout l'IUT ;
- **enseignant** / **demo** : voit seulement ses cours.

Le serveur simule le bâtiment et l'automate. Au démarrage, il joue aussi la semaine précédente en quelques secondes, pour que le registre ait déjà des séances. Dans la page de la salle SAR 200, les boutons provoquent des pannes ou des fraudes, et on voit le diagnostic les trouver.

L'assistant IA demande en plus `pip install anthropic` et une clé API Claude (voir [serveur](serveur/README.md#assistant-ia-en-option)). Sans eux, sa page dit qu'il est hors ligne et tout le reste marche.

## Ce qui est réel et ce qui est simulé

- **Réel :**
  - les 10 salles et leurs places, et les cours des groupes GEII S4 TP1 et TP2 de la semaine 11 (emplois du temps CELCAT) ;
  - les tests sur ROBOD et la salle danoise.
- **Simulé pour l'instant :**
  - le plan des étages (schématique) ;
  - les autres cours, les présences, le Wi-Fi et le CO₂ des salles.

Les pages l'indiquent dans un bandeau.

## Tests

```
python tests/test_scenarios.py     une semaine simulée : chaque panne et chaque fraude est trouvée
python tests/test_automate.py      échange Modbus et sécurité de l'automate
python tests/test_suivi.py         comptes, droits, registre des présences, corrections, export
python tests/test_prevision.py     prévisions, ventilation anticipée contre règle simple, changement de salle
python tests/test_assistant.py     assistant IA avec un faux client : aucun nom envoyé, droits, page web
```
