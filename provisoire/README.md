# IUT_de_demain : CampusTwin (dossier provisoire)

> Dossier provisoire : tout le projet est rangé ici pour l'instant, on réorganisera le dépôt en équipe.
> Les commandes se lancent depuis ce dossier `provisoire/`.
> Les noms des enseignants sont remplacés par « Enseignant A, B… » car le dépôt est public.

SAE BUT 3 GEII, IUT de Cergy-Pontoise, site de Sarcelles. Louay Boubaya, Ariel Guarise-Preller, Noah Poiré.

Le sujet de la SAE est « l'IUT de demain ». On a fait CampusTwin, un jumeau numérique du bâtiment. L'idée de départ était une salle qui comprend pourquoi son air est mauvais. On l'a ensuite étendue à tout l'IUT, pour que le directeur des études puisse voir qui est dans quelle salle.

## Ce que fait le projet

Dans la salle SAR 200, trois capteurs à la porte comptent les entrées et les sorties : un capteur de distance ToF 8×8, une caméra thermique 32×24 et un radar. On n'utilise pas de caméra classique. Dans les autres salles, le nombre de personnes est estimé avec le Wi-Fi, à 2 personnes près.

Chaque étudiant badge sa carte en entrant. Le serveur compare les badges aux passages comptés, ce qui permet de voir une entrée sans badge ou une carte prêtée. On ne garde qu'une empreinte de la carte, pas son numéro. Pour l'essai réel dans notre salle, il y a un lecteur de badge seul (XIAO + PN532) et une page du site pour donner chaque carte à un étudiant.

Avec le CO₂, le serveur calcule le débit d'air réel de la salle de deux façons : avec le comptage quand la salle est occupée, et sans le comptage quand elle se vide. En comparant les deux, et avec une mesure le soir, il sépare 5 causes : ventilation en panne, fenêtre ouverte, capteur qui dérive, comptage faux et capteur mal placé.

Le site de suivi a quatre types de comptes : directeur des études, scolarité, enseignant et services techniques. On y trouve le tableau de bord du jour, les séances avec la feuille d'émargement, les classes et la fiche de chaque étudiant. Un enseignant peut corriger un statut (oubli de badge, absence justifiée) et la correction est gardée avec son nom. Il ne voit que ses cours. On peut exporter les présences en CSV pour le CFA, par demi-journée.

Le serveur prévoit aussi le CO₂ de chaque salle pour les deux heures suivantes, avec l'emploi du temps et le taux de présence qu'il a appris pour chaque groupe. Dans SAR 200, la ventilation démarre avant l'arrivée des étudiants et s'arrête quand personne n'arrive. Sur une semaine simulée, ça fait 16 % d'énergie en moins que la règle simple, et 136 minutes au-dessus de 1000 ppm au lieu de 246. Si un cours va avoir l'air mauvais ou trop d'étudiants pour sa salle, le serveur propose une autre salle, ou un échange avec une salle occupée. Le directeur accepte ou non.

Les enseignants peuvent signaler un problème dans une salle : il manque une table, il n'y a plus de feutres, le vidéoprojecteur ne marche pas… Le serveur regarde le prochain cours dans la salle pour dire si c'est urgent, et quand la salle est libre pour intervenir. Une table manquante enlève 2 places tant que le ticket est ouvert. Le serveur ouvre aussi un ticket tout seul quand il détecte une panne de ventilation ou de capteur. Les services techniques ont leur compte et ne voient que les tickets.

Notre idée la plus nouvelle est de compter les personnes avec les ondes Wi-Fi, sans aucun capteur. Deux cartes ESP32-S3 se parlent, et quand quelqu'un bouge entre elles, le signal change. Dans SAR 200, on compare ce que voient les ondes au comptage de la porte, pour savoir si les ondes peuvent compter les étudiants d'une vraie salle de cours. Le programme des cartes et le serveur sont prêts, l'essai reste à faire.

On a aussi ajouté :
- une vérification de l'émargement par le CO₂ : le CO₂ donne le nombre de personnes qui ont été dans la salle et on le compare aux badges. Sur de vraies salles (données ROBOD), un étudiant qui badge pour 6 absents est repéré dans 68 à 92 % des cours, avec 0 à 11 % de fausses alertes ;
- les retards du RER D : quand la ligne est perturbée, le serveur prévoit combien d'étudiants arriveront en retard ;
- le chauffage et l'éclairage selon l'occupation, pilotés par l'automate dans SAR 200 (29 % d'énergie en moins estimés sur les 23 salles) ;
- un assistant IA (Claude, d'Anthropic) qui répond aux questions en français sans recevoir les noms des étudiants ;
- un plan 3D de l'IUT avec, pour chaque salle, le cours, l'enseignant, les présents et l'air ;
- un automate S7-1200 qui pilote une maquette de la ventilation, avec arrêt d'urgence et mode manuel.

## Organisation

| Dossier | Contenu | État |
| --- | --- | --- |
| [jumeau3d/suivi](jumeau3d/suivi) | Site de suivi des classes | marche, vérifié dans le navigateur |
| [jumeau3d](jumeau3d) | Plan 3D de l'IUT (`iut.html`) et salle SAR 200 en détail (`index.html`) | marche, vérifié dans le navigateur |
| [serveur](serveur) | Serveur Python | marche en simulation, assistant testé avec un faux client seulement |
| [simulateurs](simulateurs) | Bâtiment et automate simulés | marche |
| [tests](tests) | Tests du serveur sur une semaine simulée | tous passent |
| [firmware](firmware) | Code des cartes XIAO ESP32S3 (nœud salle, nœud porte, badge, ondes Wi-Fi) | compile, pas encore testé sur le matériel |
| [automate](automate) | Programme SCL du S7-1200 et branchements | écrit, pas encore compilé dans TIA Portal |
| [outils](outils) | Import de l'emploi du temps CELCAT et du Wi-Fi de la DSI | testés sur des exemples |
| [donnees_reelles](donnees_reelles) | Tests sur des données publiques (ROBOD, salle danoise OU44) | fait |
| [docs](docs) | Synthèse du projet et proposition de matériel | |

## Lancer la démo

Il faut Python 3.10 ou plus. On double-clique sur `lancer.bat`, ou on tape :

```
python serveur/serveur.py --simulation
```

Puis on ouvre http://localhost:8000. Les comptes de démo sont `directeur`, `enseignant` et `technique`, avec le mot de passe `demo`. Le serveur simule le bâtiment et l'automate, et rejoue la semaine précédente au démarrage pour avoir déjà des séances. Dans la page de la salle SAR 200, des boutons provoquent des pannes ou des fraudes.

L'assistant IA demande en plus `pip install anthropic` et une clé API Claude (voir [serveur](serveur/README.md#assistant-ia-en-option)). Sans ça, sa page indique qu'il est hors ligne et le reste marche.

## Réel ou simulé

Les 23 salles du bâtiment, leurs places et les cours de notre classe (BUT3 ESE FA S5, semaine du 16 au 20 novembre 2026) viennent de CELCAT. Les tests sur ROBOD et la salle danoise utilisent de vraies mesures.

Le reste est simulé pour l'instant : le plan des étages, les autres cours, les présences, le Wi-Fi et le CO₂. Le taux d'absence de chaque groupe est tiré entre 3 et 20 %, avec 8 % de plus le vendredi après-midi. On a aussi mis exprès un cours trop gros pour sa salle : Physique du groupe simulé 12, 28 inscrits en SAR 101 (19 places).

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
python tests/test_ondes.py         ondes Wi-Fi : salle vide apprise, présence, fichier d'apprentissage
```
