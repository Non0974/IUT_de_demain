"""Test de l'échange Modbus entre le serveur et l'automate simulé, et de la sécurité de l'automate.

    python tests/test_automate.py
"""

import sys
import time
from importlib import util
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

from automate import PontAutomate   # noqa: E402

spec = util.spec_from_file_location('automate_simule', RACINE / 'simulateurs' / 'automate.py')
simule = util.module_from_spec(spec)
spec.loader.exec_module(simule)

PORT = 5031


def attendre(pont, condition, delai=8):
    fin = time.time() + delai
    while time.time() < fin:
        if condition(pont.etat):
            return True
        time.sleep(0.2)
    return False


def main():
    automate, _ = simule.demarrer(PORT)
    pont = PontAutomate('127.0.0.1', PORT, periode=0.3)
    pont.demarrer()
    verifs = []

    pont.regler('grande', personnes=15)
    verifs.append(('connexion et consigne grande vitesse', attendre(pont, lambda e: e.get('connecte') and e.get('vitesse') == 'grande')))
    verifs.append(('électrovanne active avec 15 personnes', attendre(pont, lambda e: e.get('electrovanne'), 12)))
    pont.regler(eclairage=False, chauffage='confort')
    verifs.append(('salle vide, cours bientôt : lumière éteinte, chauffage confort (radiateur en marche)',
                   attendre(pont, lambda e: e.get('eclairage') is False and e.get('chauffage') == 'confort' and e.get('radiateur'))))

    automate.arret_urgence = True
    verifs.append(("arrêt d'urgence : ventilateur, vanne et chauffage coupés, lumière allumée",
                   attendre(pont, lambda e: e.get('arret_urgence') and e.get('vitesse') == 'arret' and not e.get('electrovanne')
                            and e.get('eclairage') and e.get('chauffage') == 'hors_gel' and not e.get('radiateur'))))
    automate.arret_urgence = False

    automate.auto = False
    verifs.append(('mode manuel : petite vitesse, lumière et chauffage confort',
                   attendre(pont, lambda e: not e.get('auto') and e.get('vitesse') == 'petite' and e.get('eclairage')
                            and e.get('chauffage') == 'confort')))
    automate.auto = True
    verifs.append(('retour en auto : consigne du serveur', attendre(pont, lambda e: e.get('auto') and e.get('vitesse') == 'grande')))

    pont.arret = True                       # le serveur se tait
    time.sleep(6.5)
    automate.cycle()
    verifs.append(('serveur muet 5 s : secours en petite vitesse, lumière allumée, chauffage réduit',
                   automate.hr[11] == 1 and bool(automate.hr[10] & 16) and bool(automate.hr[10] & 32) and automate.hr[13] == 1))

    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
