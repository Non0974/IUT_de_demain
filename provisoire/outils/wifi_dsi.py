"""Wi-Fi de la DSI -> CampusTwin : nombre d'appareils connectés à chaque borne, ramené à chaque salle.

La DSI exporte depuis le contrôleur Wi-Fi un fichier CSV : une ligne par borne et par minute
(heure, nom de la borne, nombre d'appareils). On dit dans bornes.json quelle borne couvre quelle
salle (une borne peut couvrir deux salles : on partage ses appareils). Le serveur reçoit, pour chaque
minute, {"type": "wifi", "bornes": {salle: appareils}} et son modèle transforme les appareils en
personnes (testé à ±2 personnes sur les données ROBOD).

Aucun identifiant d'appareil (adresse MAC) n'est lu ni envoyé : seulement des nombres.

    python outils/wifi_dsi.py export.csv --bornes outils/bornes.exemple.json --essai
    python outils/wifi_dsi.py export.csv --bornes bornes.json --serveur http://localhost:8000
    python outils/wifi_dsi.py dossier_dsi/ --bornes bornes.json --serveur http://localhost:8000 --suivre
"""

import argparse
import csv
import json
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Noms de colonnes reconnus (en minuscules) : chaque contrôleur exporte les siens
COLONNES = {
    'heure': ('horodatage', 'heure', 'date', 'time', 'timestamp'),
    'borne': ('borne', 'ap', 'ap name', 'ap_name', 'nom de la borne', 'access point', 'name'),
    'appareils': ('appareils', 'clients', 'client count', 'nombre de clients', 'nb clients', 'count', 'associated clients'),
}


def trouver_colonnes(entete, forcees=None):
    """Quelle colonne contient l'heure, la borne, le nombre d'appareils."""
    forcees = forcees or {}
    bas = [c.strip().lower() for c in entete]
    trouvees = {}
    for role, noms in COLONNES.items():
        if forcees.get(role):
            trouvees[role] = bas.index(forcees[role].strip().lower())
            continue
        indice = next((bas.index(n) for n in noms if n in bas), None)
        if indice is None:
            raise ValueError(f'Colonne « {role} » introuvable dans {entete}. Préciser --colonne-{role}.')
        trouvees[role] = indice
    return trouvees


def lire_heure(texte):
    texte = texte.strip()
    if texte.replace('.', '', 1).isdigit():                    # secondes depuis 1970
        return float(texte)
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M'):
        try:
            return datetime.strptime(texte, fmt).timestamp()
        except ValueError:
            pass
    raise ValueError(f'Heure illisible : {texte}')


def lire_csv(chemin, forcees=None):
    """Lignes (t, borne, appareils) du fichier, quel que soit le séparateur (, ou ;)."""
    texte = Path(chemin).read_text(encoding='utf-8-sig')
    dialecte = csv.Sniffer().sniff(texte.splitlines()[0], delimiters=',;\t')
    lignes = list(csv.reader(texte.splitlines(), dialecte))
    col = trouver_colonnes(lignes[0], forcees)
    return [(lire_heure(l[col['heure']]), l[col['borne']].strip(), int(float(l[col['appareils']])))
            for l in lignes[1:] if l and len(l) > max(col.values())]


def par_minute(lignes, bornes):
    """Messages pour le serveur : une minute = les appareils de chaque salle. Renvoie aussi les bornes inconnues."""
    minutes = defaultdict(lambda: defaultdict(float))
    inconnues = set()
    for t, borne, appareils in lignes:
        if borne not in bornes:
            inconnues.add(borne)
            continue
        for salle, part in bornes[borne].items():
            minutes[int(t // 60) * 60][salle] += appareils * part
    messages = [{'type': 'wifi', 't': float(m), 'bornes': {s: round(n) for s, n in sorted(v.items())}}
                for m, v in sorted(minutes.items())]
    return messages, sorted(inconnues)


def envoyer(messages, serveur, cle=''):
    if not messages:
        return
    req = urllib.request.Request(f'{serveur.rstrip("/")}/api/mesure', data=json.dumps(messages).encode(),
                                 headers={'Content-Type': 'application/json', 'X-Cle': cle}, method='POST')
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


def main():
    p = argparse.ArgumentParser(description='Wi-Fi de la DSI vers CampusTwin')
    p.add_argument('source', help='fichier CSV exporté par la DSI, ou dossier où elle en dépose (avec --suivre)')
    p.add_argument('--bornes', required=True, help='fichier JSON : borne -> {salle: part}')
    p.add_argument('--serveur', default='http://localhost:8000')
    p.add_argument('--cle', default='', help='clé des capteurs (CLE_CAPTEURS du serveur)')
    p.add_argument('--essai', action='store_true', help='affiche ce qui serait envoyé, sans rien envoyer')
    p.add_argument('--suivre', action='store_true', help='surveille le dossier et envoie chaque nouveau fichier')
    for role in COLONNES:
        p.add_argument(f'--colonne-{role}', help=f'nom de la colonne « {role} » si elle n\'est pas reconnue')
    a = p.parse_args()
    bornes = json.loads(Path(a.bornes).read_text(encoding='utf-8'))
    forcees = {r: getattr(a, f'colonne_{r}') for r in COLONNES}

    def traiter(fichier):
        messages, inconnues = par_minute(lire_csv(fichier, forcees), bornes)
        if inconnues:
            print(f'{fichier.name} : bornes absentes de {a.bornes} (ignorées) : {", ".join(inconnues)}')
        if a.essai:
            for m in messages:
                print(datetime.fromtimestamp(m['t']).strftime('%d/%m %H:%M'), m['bornes'])
        else:
            envoyer(messages, a.serveur, a.cle)
            print(f'{fichier.name} : {len(messages)} minute(s) envoyée(s)')

    source = Path(a.source)
    if not a.suivre:
        traiter(source)
        return
    vus = set()
    print(f'Surveillance de {source} (Ctrl+C pour arrêter)')
    while True:
        for fichier in sorted(source.glob('*.csv')):
            if fichier not in vus:
                try:
                    traiter(fichier)
                    vus.add(fichier)
                except (OSError, ValueError) as e:      # fichier en cours d'écriture, serveur absent : on réessaiera
                    print(f'{fichier.name} : {e}', file=sys.stderr)
        time.sleep(20)


if __name__ == '__main__':
    main()
