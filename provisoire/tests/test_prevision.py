"""Test du jumeau prédictif : précision des prévisions, ventilation anticipée, réaffectation des salles.

Une semaine simulée deux fois sur la salle de l'automate (SAR 200) :
  - avec la règle simple d'avant (ventilation selon le nombre de personnes) ;
  - avec la commande prédictive du jumeau.
On compare l'énergie et les minutes de mauvais air vraiment simulées. Puis on accepte une
proposition de changement de salle et on vérifie que le cours a bien eu lieu ailleurs, avec un
meilleur air que prévu dans sa salle d'origine.

    python tests/test_prevision.py
"""

import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import config      # noqa: E402
import serveur     # noqa: E402
from registre import Registre   # noqa: E402
from salle import heure_du_jour  # noqa: E402

SALLE = config.SALLE_AUTOMATE


class PontFactice:
    def __init__(self):
        self.etat = {'connecte': False}

    def regler(self, consigne=None, personnes=None):
        pass


def semaine(strategie, jours=5, avant_chaque_minute=None):
    campus = serveur.Campus(None, PontFactice(), Registre())
    campus.mode['strategie'] = strategie
    sim = serveur.charger_simulateur('batiment').SimulateurBatiment(
        campus.recevoir, lambda s: campus.salles[s].niveau or 'petite', cours_du_jour=campus.planning.cours_du_jour)
    campus.simulation = sim
    campus.t = sim.t
    campus.ajouter_cartes(sim.annuaire())
    debut = datetime.fromtimestamp(sim.t).date()
    vrai = {'energie': 0.0, 'minutes_1000': 0, 'minutes_800': 0}
    n = 0
    while (datetime.fromtimestamp(sim.t).date() - debut).days < jours:
        sim.pas(10)
        n += 1
        if n % 6 == 0:                                      # chaque minute simulée
            campus.piloter()
            campus.synchroniser(force=True)
            s = sim.salles[SALLE]
            vrai['energie'] += campus.commande.puissance(s.niveau) / 60
            vrai['minutes_1000'] += s.C > 1000
            vrai['minutes_800'] += s.C > 800
            if avant_chaque_minute:
                avant_chaque_minute(campus, sim)
    return campus, vrai


def main():
    verifs = []

    regle, vrai_regle = semaine('reactive')
    jumeau, vrai_jumeau = semaine('predictive')
    print('Salle SAR 200, une semaine simulée (vrai CO2 de la simulation) :')
    for nom, v in (('règle simple', vrai_regle), ('jumeau prédictif', vrai_jumeau)):
        print(f'  {nom:17} {v["energie"]:6.1f} kWh   {v["minutes_1000"]:4d} min > 1000 ppm   {v["minutes_800"]:4d} min > 800 ppm')
    economie = 1 - vrai_jumeau['energie'] / vrai_regle['energie']
    print(f'  économie d\'énergie : {economie:.0%}')
    verifs.append(('le jumeau dépense moins d\'énergie que la règle simple', economie > 0.05))
    verifs.append(('sans plus de minutes au-dessus de 1000 ppm',
                   vrai_jumeau['minutes_1000'] <= vrai_regle['minutes_1000'] + 10))

    p = jumeau.prevision.precision()
    print(f'Précision des prévisions (toutes salles) : {p}')
    verifs.append(('erreur moyenne à 30 min < 120 ppm', p['30 min']['erreur_moyenne'] is not None and p['30 min']['erreur_moyenne'] < 120))
    verifs.append(('erreur moyenne à 60 min < 180 ppm', p['60 min']['erreur_moyenne'] is not None and p['60 min']['erreur_moyenne'] < 180))

    # Réaffectation : après une semaine d'apprentissage (les salles connaissent leur débit), le lundi
    # suivant à 7 h 50, on accepte la première proposition et on regarde ce qui se passe
    acceptee = {}
    debut_test = datetime.fromtimestamp(serveur.charger_simulateur('batiment').DEBUT_SEMAINE.timestamp()).date()

    def regarder(campus, sim):
        d = datetime.fromtimestamp(campus.t)
        if acceptee or (d.date() - debut_test).days != 7 or d.hour != 7 or d.minute != 50:
            return
        props = campus.previsions()['propositions']
        print(f'Lundi suivant, 7 h 50 : {len(props)} proposition(s)')
        for x in props:
            print(f'  {x["matiere"]} ({x["groupes"][0]}) {x["salle"]} -> {x["proposee"]} : pic prévu {x["pic"]} -> {x["pic_propose"]} ppm')
        if props:
            x = props[0]
            campus.planning.changer_salle(d.date(), x['cours'], x['proposee'], 'test', campus.t)
            acceptee.update(x, jour=d.date())

    campus, _ = semaine('predictive', jours=8, avant_chaque_minute=regarder)
    verifs.append(('au moins une proposition de changement de salle', bool(acceptee)))
    if acceptee:
        sid = f'{acceptee["jour"].isoformat()}_{acceptee["cours"]}'
        s = campus.registre.seance(sid)
        verifs.append(('le cours a bien eu lieu dans la salle proposée', s is not None and s['salle'] == acceptee['proposee']))
        debut, fin = acceptee['debut'], acceptee['fin']
        mesures = [c for t, c, _ in campus.salles[acceptee['proposee']].historique
                   if datetime.fromtimestamp(t).date() == acceptee['jour'] and debut <= heure_du_jour(t) <= fin]
        print(f'  pic mesuré dans la nouvelle salle : {max(mesures):.0f} ppm (prévu {acceptee["pic_propose"]}, '
              f'{acceptee["pic"]} prévus dans l\'ancienne)' if mesures else '  pas de mesure')
        verifs.append(('l\'air y est resté meilleur que prévu dans l\'ancienne salle', bool(mesures) and max(mesures) < acceptee['pic'] - 150))

    print()
    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
