"""Test de l'import du Wi-Fi de la DSI : fichier exemple -> appareils par salle -> serveur.

    python tests/test_wifi_dsi.py
"""

import json
import sys
from importlib import util
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import serveur                      # noqa: E402
from registre import Registre       # noqa: E402

spec = util.spec_from_file_location('wifi_dsi', RACINE / 'outils' / 'wifi_dsi.py')
wifi = util.module_from_spec(spec)
spec.loader.exec_module(wifi)


class PontFactice:
    etat = {'connecte': False}

    def regler(self, *a, **k):
        pass


def main():
    verifs = []
    bornes = json.loads((RACINE / 'outils' / 'bornes.exemple.json').read_text(encoding='utf-8'))
    lignes = wifi.lire_csv(RACINE / 'outils' / 'export_dsi.exemple.csv')
    verifs.append(('fichier lu (séparateur ; et noms de colonnes du contrôleur)', len(lignes) == 8 and lignes[0][1:] == ('AP-SAR-102', 21)))
    messages, inconnues = wifi.par_minute(lignes, bornes)
    verifs.append(('une minute = un message', len(messages) == 2 and all(m['type'] == 'wifi' for m in messages)))
    verifs.append(('borne partagée : appareils coupés en deux', messages[1]['bornes']['SAR 101'] == 3 and messages[1]['bornes']['SAR 103'] == 3))
    verifs.append(('borne du couloir inconnue : signalée et ignorée', inconnues == ['AP-COULOIR-1']))

    campus = serveur.Campus(None, PontFactice(), Registre())
    for m in messages:
        campus.recevoir(m)
    s = campus.salles['SAR 102']
    verifs.append(('le serveur reçoit les appareils et estime les personnes', s.appareils == 22 and s.n_wifi is not None and s.n_wifi > 0))

    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
