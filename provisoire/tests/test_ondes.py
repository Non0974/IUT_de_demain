"""Test de la mesure par les ondes Wi-Fi, côté serveur : messages des deux cartes ESP32-S3 (simulés),
apprentissage de la salle vide, présence, fichier d'apprentissage et analyse.

La relation entre le mouvement et le nombre de personnes est INVENTÉE dans le simulateur : ce test
vérifie la chaîne (cartes -> serveur -> fichier -> analyse), pas que les ondes comptent vraiment.
Ça, seul l'essai dans la salle le dira.

    python tests/test_ondes.py
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))
sys.path.insert(0, str(RACINE / 'outils'))

import serveur      # noqa: E402
import ondes_wifi   # noqa: E402
from registre import Registre   # noqa: E402

SALLE = 'SAR 200'


class PontFactice:
    etat = {'connecte': False}

    def regler(self, *a, **k):
        pass


def main():
    verifs = []
    campus = serveur.Campus(None, PontFactice(), Registre())
    fichier = Path(tempfile.mkdtemp()) / 'ondes.csv'
    campus.fichier_ondes = fichier
    sim = serveur.charger_simulateur('batiment').SimulateurBatiment(
        campus.recevoir, lambda s: campus.salles[s].niveau or 'petite', cours_du_jour=campus.planning.cours_du_jour)
    campus.simulation = sim
    campus.t = sim.t
    campus.ajouter_cartes(sim.annuaire())
    debut = datetime.fromtimestamp(sim.t).date()
    salle = campus.salles[SALLE]
    accord = []
    derniere = None
    n = 0
    while (datetime.fromtimestamp(sim.t).date() - debut).days < 2:
        sim.pas(10)
        campus.t = sim.t
        n += 1
        if n % 6 == 0:
            campus.piloter()
        e = salle.ondes.etat(sim.t)
        derniere = e or derniere
        if e and e['etat'] == 'ok' and n % 6 == 0:
            accord.append(e['presence'] == (salle.n_porte > 0))

    e = derniere
    print(f'Dernière mesure : {e}')
    verifs.append(('les ondes arrivent et le niveau de la salle vide est appris', e is not None and e['etat'] == 'ok'
                   and e['seuil'] is not None))
    taux = sum(accord) / len(accord) if accord else 0
    print(f'Présence par les ondes d\'accord avec le comptage de la porte : {taux:.0%} ({len(accord)} instants)')
    verifs.append(('présence par les ondes d\'accord avec la porte (simulation)', taux >= 0.9))

    lignes = fichier.read_text(encoding='utf-8').splitlines()
    entete = lignes[0].split(';')
    derniere = lignes[-1].split(';')
    verifs.append(('fichier d\'apprentissage : mesure, vrai nombre de personnes et 52 amplitudes',
                   len(lignes) > 1000 and len(entete) == 9 + 52 and len(derniere) == len(entete) and derniere[6] != ''))

    r = ondes_wifi.analyser(ondes_wifi.lire(fichier, SALLE))
    print(f"Analyse : présence juste {r['presence_juste']:.0%}, comptage à {r['erreur']:.1f} près "
          f"(sans les ondes : {r['erreur_sans_ondes']:.1f})")
    verifs.append(('l\'analyse tourne et fait mieux que « toujours la moyenne » (simulation)',
                   r['erreur'] < r['erreur_sans_ondes']))

    campus.recevoir({'type': 'ondes', 'salle': SALLE, 'paquets': 3, 'mouvement': 0.5, 't': sim.t + 1})
    verifs.append(('émetteur éteint : pas d\'avis', salle.ondes.etat(sim.t + 1)['etat'] == 'emetteur'
                   and salle.ondes.etat(sim.t + 1)['presence'] is None))

    print()
    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
