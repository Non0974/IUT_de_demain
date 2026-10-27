"""Test du RER qui prévient la salle : lecture d'un message PRIM (SIRI Lite), puis deux semaines
simulées où le RER D est perturbé certains matins. Le jumeau apprend combien d'étudiants arrivent en
retard, prévient avant les cours, et explique les retards sur la fiche de la séance.

    python tests/test_transports.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import serveur     # noqa: E402
from registre import Registre  # noqa: E402
from salle import heure_du_jour  # noqa: E402
from suivi import Suivi        # noqa: E402
from transports import perturbations_siri  # noqa: E402

DIRECTEUR = {'login': 'directeur', 'role': 'directeur', 'nom': 'Directeur', 'enseignant': None}
SIRI = {'Siri': {'ServiceDelivery': {'GeneralMessageDelivery': [{'InfoMessage': [
    {'InfoChannelRef': {'value': 'Perturbation'},
     'Content': {'LineRef': [{'value': 'STIF:Line::C01728:'}], 'Message': [{'MessageText': {'value': 'RER D : trafic perturbé'}}]}},
    {'InfoChannelRef': {'value': 'Information'},
     'Content': {'LineRef': [{'value': 'STIF:Line::C01728:'}], 'Message': [{'MessageText': {'value': 'Travaux ce week-end'}}]}},
    {'InfoChannelRef': {'value': 'Perturbation'},
     'Content': {'LineRef': [{'value': 'STIF:Line::C01742:'}], 'Message': [{'MessageText': {'value': 'RER A : incident'}}]}},
]}]}}}


class PontFactice:
    etat = {'connecte': False}

    def regler(self, *a, **k):
        pass


def main():
    verifs = []
    verifs.append(('message PRIM : seules les perturbations du RER D sont gardées',
                   perturbations_siri(SIRI, 'STIF:Line::C01728:') == ['RER D : trafic perturbé']))

    module = serveur.charger_simulateur('batiment')
    campus = serveur.Campus(None, PontFactice(), Registre())
    sim = module.SimulateurBatiment(campus.recevoir, lambda s: campus.salles[s].niveau or 'petite',
                                    cours_du_jour=campus.planning.cours_du_jour)
    campus.simulation = sim
    campus.t = sim.t
    campus.ajouter_cartes(sim.annuaire())
    debut = datetime.fromtimestamp(sim.t).date()
    jours = [debut + timedelta(days=k) for k in range(14)]
    perturbes = [j for j in jours if module.perturbation_rer(datetime(j.year, j.month, j.day))]
    calmes = [j for j in jours if j.weekday() < 5 and j not in perturbes]
    print(f'RER D perturbé : {", ".join(f"{j:%a %d/%m}" for j in perturbes)}')

    suivi = Suivi(campus)
    prevus = {}          # séance -> retards prévus
    alertes_calmes = []
    n = 0
    while (datetime.fromtimestamp(sim.t).date() - debut).days < 14:
        sim.pas(10)
        campus.t = sim.t
        n += 1
        if n % 6:
            continue
        campus.piloter()
        campus.synchroniser(force=True)
        jour = datetime.fromtimestamp(sim.t).date()
        h = heure_du_jour(sim.t)
        if jour in calmes and abs(h - 7.5) < 0.01:
            alertes_calmes += [a for a in suivi.tableau(DIRECTEUR)['alertes'] if a.get('transport')]
        # Semaine 2, dès que la perturbation est annoncée : ce que le jumeau prévoit pour les cours qui arrivent
        if jour in perturbes and jour >= debut + timedelta(days=7) and campus.transports.maintenant(sim.t) and not any(
                s.startswith(jour.isoformat()) for s in prevus):
            normal, perturbe, vues = campus.transports.taux('RER D')
            for c in campus.planning.cours_du_jour(jour):
                if c['salle'] and h <= c['debut'] <= h + 1.5 and perturbe is not None:
                    prevus[f'{jour.isoformat()}_{c["id"]}'] = round(campus.prevision.etudiants_attendus(c, jour) * perturbe)
            alertes = [a for a in suivi.tableau(DIRECTEUR)['alertes'] if a.get('transport')]
            print(f'{jour:%a %d/%m} {h:.2f} h, RER D perturbé : {len(alertes)} alerte(s), par exemple « {alertes[0]["texte"] if alertes else ""} »')

    normal, perturbe, vues = campus.transports.taux('RER D')
    print(f'Appris : {normal:.0%} de retards d\'habitude, {perturbe:.0%} quand le RER D est perturbé ({vues} séances)')
    verifs.append(('appris : bien plus de retards quand le RER D est perturbé', perturbe is not None and perturbe > normal + 0.1))
    ecarts = []
    for sid, prevu in prevus.items():
        s = campus.registre.seance(sid)
        if s:
            ecarts.append(abs(prevu - s['retards']))
            print(f'  {s["matiere"]} {s["salle"]} : {prevu} retards prévus, {s["retards"]} vrais')
    verifs.append(('retards prévus à 3 près en moyenne', ecarts and sum(ecarts) / len(ecarts) <= 3))
    explications = [suivi.seance(DIRECTEUR, sid).get('transport') for sid in prevus if campus.registre.seance(sid)]
    verifs.append(('fiche de la séance : retards expliqués par le RER D', explications and all(explications)))
    verifs.append(('pas d\'alerte les matins sans perturbation', not alertes_calmes))

    print()
    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
