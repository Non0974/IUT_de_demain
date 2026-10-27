"""Test du chauffage et de l'éclairage selon l'occupation : règles, puis une journée simulée comparée à
l'horaire fixe d'avant (salle de l'automate et tout le bâtiment).

    python tests/test_ambiance.py
"""

import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import config      # noqa: E402
import serveur     # noqa: E402
from ambiance import decider   # noqa: E402
from registre import Registre  # noqa: E402
from salle import heure_du_jour  # noqa: E402


class PontFactice:
    def __init__(self):
        self.etat = {'connecte': False}
        self.reglages = []

    def regler(self, consigne=None, personnes=None, **ambiance):
        self.reglages.append(ambiance)


def main():
    verifs = []
    cours = [{'debut': 8.5, 'fin': 10.5}]
    verifs.append(('45 min avant le cours : chauffage confort, lumière encore éteinte', decider(cours, 7.8, 0, 0) == (False, 'confort')))
    verifs.append(('arrivée des étudiants : lumière allumée', decider(cours, 8.45, 0, 0)[0]))
    verifs.append(('entre deux cours, salle vide : réduit, lumière éteinte', decider(cours, 11.5, 0, 0) == (False, 'reduit')))
    verifs.append(('la nuit : hors-gel', decider(cours, 22.0, 0, 0) == (False, 'hors_gel')))
    verifs.append(('week-end, salle vide : hors-gel', decider([], 10.0, 5, 0) == (False, 'hors_gel')))
    verifs.append(('quelqu\'un dans la salle, même le week-end : confort et lumière', decider([], 15.0, 6, 2) == (True, 'confort')))

    # Une journée de cours simulée (lundi, 7 h – 20 h 30), avec le vrai planning
    pont = PontFactice()
    campus = serveur.Campus(None, pont, Registre())
    sim = serveur.charger_simulateur('batiment').SimulateurBatiment(
        campus.recevoir, lambda s: campus.salles[s].niveau or 'petite', cours_du_jour=campus.planning.cours_du_jour)
    campus.simulation = sim
    campus.t = sim.t
    campus.ajouter_cartes(sim.annuaire())
    jour = datetime.fromtimestamp(sim.t).date()
    premier = min((c for c in campus.planning.cours_du_jour(jour) if c['salle'] == config.SALLE_AUTOMATE), key=lambda c: c['debut'])
    avant_cours = None
    n = 0
    while heure_du_jour(sim.t) < 20.5 and datetime.fromtimestamp(sim.t).date() == jour:   # avant le saut de nuit du simulateur
        sim.pas(10)
        campus.t = sim.t
        n += 1
        if n % 6 == 0:
            campus.piloter()
            campus.synchroniser(force=True)
            if avant_cours is None and heure_du_jour(sim.t) >= premier['debut'] - 0.5:
                avant_cours = (campus.ambiance, campus.salles[config.SALLE_AUTOMATE].nombre())
    b = campus.bilan_ambiance.resume()
    print(f'{config.SALLE_AUTOMATE} : premier cours à {premier["debut"]:.2f} h ; 30 min avant : {avant_cours}')
    print(f'Énergie du lundi, {config.SALLE_AUTOMATE} : {b["salle"]["jumeau"]} kWh contre {b["salle"]["fixe"]} kWh (horaire fixe) ; '
          f'confort {b["heures_confort"]["jumeau"]} h contre {b["heures_confort"]["fixe"]} h')
    print(f'Tout le bâtiment ({len(campus.batiment["salles"])} salles) : {b["batiment"]["jumeau"]} kWh contre {b["batiment"]["fixe"]} kWh '
          f'(économie {b["batiment"]["economie"]:.0%})')
    verifs.append(('préchauffage : confort 30 min avant le premier cours de la salle', avant_cours and avant_cours[0][1] == 'confort'))
    verifs.append(('consignes envoyées à l\'automate', pont.reglages and all('eclairage' in r and 'chauffage' in r for r in pont.reglages)))
    verifs.append(('salle de l\'automate : moins d\'énergie que l\'horaire fixe', b['salle']['jumeau'] < b['salle']['fixe']))
    verifs.append(('bâtiment : moins d\'énergie que l\'horaire fixe', b['batiment']['economie'] is not None and b['batiment']['economie'] > 0.05))

    print()
    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
