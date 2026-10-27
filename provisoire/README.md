# IUT_de_demain — CampusTwin (dossier provisoire)

> Dossier provisoire : tout le projet est rangé ici pour l'instant, on réorganisera le dépôt en équipe.
> Les commandes se lancent depuis ce dossier `provisoire/`.
> Les noms des enseignants sont remplacés par « Enseignant A, B… » (dépôt public).

SAE BUT 3 GEII, IUT de Cergy-Pontoise, site de Sarcelles. Louay Boubaya, Ariel Guarise-Preller, Noah Poiré.

Le sujet est « l'IUT de demain ». On a fait CampusTwin, un jumeau numérique du bâtiment : le directeur des études voit qui est dans quelle salle, l'émargement se fait avec la carte étudiante, et le serveur surveille l'air et les places des salles.

## Ce que fait le projet

### Compter les personnes et faire l'émargement

- À la porte de la salle SAR 200, trois capteurs comptent les passages : un ToF 8×8, une caméra thermique 32×24 et un radar. Pas de caméra classique.
- Dans les autres salles, le nombre de personnes vient du Wi-Fi (à ±2 personnes).
- Chaque étudiant badge sa carte (NFC) en entrant. On compare les badges aux passages : on voit une entrée sans badge ou une carte prêtée. On ne garde qu'une empreinte de la carte (RGPD).
- Pour l'essai réel : un lecteur de badge seul (XIAO + PN532, LED verte ou orange) et une page « Cartes » pour donner chaque carte à un étudiant.

### Diagnostic de l'air

Le CO₂ donne le débit d'air réel de la salle de deux façons : avec le comptage quand la salle est occupée, et sans le comptage quand elle se vide. En comparant les deux, plus une mesure le soir, on sépare 5 causes : ventilation en panne, fenêtre ouverte, capteur qui dérive, comptage faux, capteur mal placé.

### Site de suivi des classes

Comptes : directeur des études, scolarité, enseignant, services techniques.

- Tableau de bord : séances en cours, présents, absents, alertes.
- Séances du jour et feuille d'émargement imprimable.
- Une classe sur la semaine (étudiants × séances) et la fiche de chaque étudiant.
- Un enseignant peut corriger un statut (oubli de badge, absence justifiée). La correction est gardée avec son nom, l'heure et le motif.
- Export CSV pour le CFA, avec la présence par demi-journée.
- Un enseignant ne voit que ses cours et ses classes.
- Anticipation : CO₂ prévu, ventilation, places des salles, changements de salle proposés.
- Tickets : il manque une table, des feutres, le vidéoprojecteur ne marche pas…
- Assistant IA : on pose une question en français.

### Prévisions

- Le serveur prévoit le CO₂ de chaque salle pour les 2 heures suivantes, à partir de l'emploi du temps, du taux de présence et du débit d'air mesuré.
- Dans SAR 200, la ventilation démarre avant l'arrivée des étudiants et s'arrête quand personne n'arrive. Sur une semaine simulée : 16 % d'énergie en moins que la règle simple, et 136 minutes au-dessus de 1000 ppm au lieu de 246.
- Le serveur apprend le taux de présence de chaque groupe et de chaque demi-journée (on vient moins le vendredi après-midi). Il prévoit le nombre d'étudiants de chaque cours à 1,4 près en moyenne.
- Si l'air d'un cours va dépasser 1200 ppm, ou s'il y a plus d'étudiants que de places, il propose une autre salle. Si aucune n'est libre, une salle occupée peut proposer un échange. Le directeur accepte ou non.

### Tickets

- Un enseignant signale un problème dans une salle (table, chaise, feutres, vidéoprojecteur, chauffage…).
- Le serveur regarde l'emploi du temps : le ticket est urgent si le prochain cours n'a plus assez de places, ou s'il manque de quoi faire cours dans moins de 2 h. Il indique aussi quand la salle est libre pour intervenir.
- Une table manquante enlève 2 places tant que le ticket est ouvert. La capacité et les propositions de salle en tiennent compte.
- Le serveur ouvre aussi un ticket quand il détecte une panne de ventilation ou de capteur.
- Le service technique a son compte et ne voit que les tickets.

### Autres fonctions

- Vérification de l'émargement par le CO₂ : le CO₂ donne le nombre de personnes qui ont été dans la salle, on le compare aux badges. Testé sur de vraies salles (ROBOD) : un étudiant qui badge pour 6 absents est repéré dans 68 à 92 % des cours selon la salle, avec 0 à 11 % de fausses alertes. Une ou deux cartes en trop ne se voient pas.
- RER D : quand la ligne est perturbée, le serveur prévoit combien d'étudiants arriveront en retard à chaque cours.
- Chauffage et éclairage : la lumière s'allume seulement quand il y a quelqu'un, le chauffage passe en confort pendant les cours et 45 min avant. Sur un lundi simulé, les 23 salles consommeraient 29 % de moins qu'avec l'horaire fixe (estimation).
- Assistant IA (Claude, d'Anthropic) : il ne reçoit aucun nom (les étudiants deviennent ETU-001…, les enseignants « Enseignant A »…), il a les droits de la personne connectée et ne modifie rien.
- Plan 3D de l'IUT : pour chaque salle, le cours, l'enseignant, les présents et l'air.
- Automate S7-1200 : il pilote une maquette de la ventilation, avec arrêt d'urgence, mode manuel et repli si le serveur ne répond plus.

## Organisation

| Dossier | Contenu | État |
| --- | --- | --- |
| [jumeau3d/suivi](jumeau3d/suivi) | Site de suivi des classes | marche, vérifié dans le navigateur |
| [jumeau3d](jumeau3d) | Plan 3D de l'IUT (`iut.html`) et salle SAR 200 en détail (`index.html`) | marche, vérifié dans le navigateur |
| [serveur](serveur) | Serveur Python : capteurs, diagnostic, présences, comptes, prévisions, ventilation, automate, tickets, assistant IA | marche en simulation (assistant testé avec un faux client seulement) |
| [simulateurs](simulateurs) | Bâtiment simulé (mêmes messages que les vraies cartes) et automate simulé (Modbus TCP) | marche |
| [tests](tests) | Tests du serveur sur une semaine simulée | tous passent |
| [firmware](firmware) | Code des cartes XIAO ESP32S3 : nœud salle, nœud porte, lecteur de badge | compile, pas encore testé sur le matériel |
| [automate](automate) | Programme SCL du S7-1200 et branchements | écrit, pas encore compilé dans TIA Portal |
| [outils](outils) | Import de l'emploi du temps CELCAT et du Wi-Fi de la DSI | testés sur des exemples |
| [donnees_reelles](donnees_reelles) | Tests sur des données publiques (ROBOD, salle danoise OU44) | fait |
| [docs](docs) | Synthèse du projet et proposition de matériel | |

## Lancer la démo (sans matériel)

Il faut Python 3.10 ou plus. Double-cliquer sur `lancer.bat`, ou :

```
python serveur/serveur.py --simulation
```

Puis ouvrir http://localhost:8000. Comptes de démo (mot de passe `demo`) :
- `directeur` : tout l'IUT ;
- `enseignant` : seulement ses cours ;
- `technique` : seulement les tickets.

Le serveur simule le bâtiment et l'automate. Au démarrage, il rejoue la semaine précédente en quelques secondes pour avoir déjà des séances. Dans la page de la salle SAR 200, des boutons provoquent des pannes ou des fraudes.

L'assistant IA demande en plus `pip install anthropic` et une clé API Claude (voir [serveur](serveur/README.md#assistant-ia-en-option)). Sans ça, sa page indique qu'il est hors ligne et le reste marche.

## Réel ou simulé

Réel :
- les 23 salles du bâtiment et leurs places (CELCAT) ;
- les cours de notre classe, BUT3 ESE FA S5, semaine du 16 au 20 novembre 2026 (CELCAT) ;
- les tests sur ROBOD et la salle danoise.

Simulé pour l'instant :
- le plan des étages (schématique) ;
- les autres cours, les présences, le Wi-Fi et le CO₂ ;
- le taux d'absence de chaque groupe (3 à 20 %, plus 8 % le vendredi après-midi) ;
- un cours trop gros pour sa salle, exprès : Physique du groupe simulé 12, 28 inscrits en SAR 101 (19 places).

## Tests

```
python tests/test_scenarios.py     une semaine simulée : chaque panne et chaque fraude est trouvée
python tests/test_automate.py      échange Modbus et sécurité de l'automate
python tests/test_suivi.py         comptes, droits, registre des présences, corrections, export
python tests/test_prevision.py     prévisions, ventilation, présence apprise, places, changement de salle
python tests/test_assistant.py     assistant IA avec un faux client : aucun nom envoyé, droits
python tests/test_ambiance.py      chauffage et éclairage
python tests/test_wifi_dsi.py      import du Wi-Fi de la DSI
python tests/test_celcat.py        import d'un export CELCAT
python tests/test_temoin.py        vérification de l'émargement par le CO₂
python tests/test_transports.py    RER perturbé : retards prévus
python tests/test_negociation.py   échange de salles
python tests/test_tickets.py       tickets : urgence, places perdues, droits, panne détectée
```
