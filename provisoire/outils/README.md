# Outils

Petits programmes pour brancher CampusTwin sur les vraies données de l'IUT.

## Emploi du temps CELCAT : `celcat.py`

Met à jour `jumeau3d/donnees/edt.json` (les cours) et `salles.json` (les salles) depuis CELCAT.

1. Se connecter à https://celcat-calendar.cyu.fr, ouvrir la semaine voulue (vue Semaine).
2. F12 > Console : coller [celcat_export.js](celcat_export.js). Le navigateur télécharge `celcat_AAAA-MM-JJ.json`.
3. Importer :
   ```
   python outils/celcat.py celcat_2026-11-16.json --lundi 2026-11-16 --essai
   python outils/celcat.py celcat_2026-11-16.json --lundi 2026-11-16
   ```

Le script fusionne les créneaux qui se suivent, coupe en deux un cours donné dans deux salles, ajoute les salles qu'il ne connaît pas, et déplace (ou retire) les cours simulés qui gênent. Les enseignants deviennent « Enseignant A, B… » ; leurs vrais noms vont dans `serveur/enseignants.json`, qui reste sur le PC.

**Limite :** un compte étudiant ne voit que son propre emploi du temps. Pour avoir toutes les salles, il faut un compte qui les voit (directeur des études, scolarité) : mettre `TOUTES_LES_SALLES = true` dans `celcat_export.js` (pas encore testé, faute d'un tel compte).

## Wi-Fi de la DSI : `wifi_dsi.py`

Compte les personnes dans toutes les salles sans matériel : la DSI exporte, depuis le contrôleur Wi-Fi, le nombre d'appareils connectés à chaque borne, chaque minute (CSV : heure, borne, appareils). Aucune adresse MAC n'est demandée.

1. Dire quelle borne couvre quelle salle dans un fichier comme [bornes.exemple.json](bornes.exemple.json). Une borne qui couvre deux salles est partagée (`{"SAR 101": 0.5, "SAR 103": 0.5}`).
2. Lancer :
   ```
   python outils/wifi_dsi.py export.csv --bornes bornes.json --essai
   python outils/wifi_dsi.py export.csv --bornes bornes.json --serveur http://localhost:8000
   python outils/wifi_dsi.py dossier_dsi/ --bornes bornes.json --suivre
   ```

Le serveur transforme les appareils en personnes (modèle testé à ±2 personnes sur les données ROBOD). Exemple de fichier : [export_dsi.exemple.csv](export_dsi.exemple.csv).
