"""Test des salles qui négocient : la Physique du groupe simulé 12 (24 étudiants attendus, 19 places en
SAR 101) ne trouve aucune salle de TD libre assez grande, car on les remplit toutes à 10 h 30. SAR 109
accueille un tutorat de 5 étudiants : elle doit proposer un échange (ils tiennent en SAR 101, et l'air y reste
correct ; avec 10, SAR 101, très mal ventilée, dépasserait 1200 ppm et l'échange est refusé). On accepte,
et on vérifie que chacun a eu sa place.

    python tests/test_negociation.py
"""

import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import serveur     # noqa: E402
from capacite import libre     # noqa: E402
from registre import Registre  # noqa: E402
from salle import heure_du_jour  # noqa: E402


class PontFactice:
    etat = {'connecte': False}

    def regler(self, *a, **k):
        pass


def main():
    verifs = []
    campus = serveur.Campus(None, PontFactice(), Registre())
    sim = serveur.charger_simulateur('batiment').SimulateurBatiment(
        campus.recevoir, lambda s: campus.salles[s].niveau or 'petite', cours_du_jour=campus.planning.cours_du_jour)
    campus.simulation = sim
    campus.t = sim.t
    campus.ajouter_cartes(sim.annuaire())
    debut = datetime.fromtimestamp(sim.t).date()

    def jouer(jour, heure):
        """Joue jusqu'au jour et à l'heure demandés (le simulateur saute les nuits et les week-ends)."""
        n = 0
        while (datetime.fromtimestamp(sim.t).date() - debut).days < jour or (
                (datetime.fromtimestamp(sim.t).date() - debut).days == jour and heure_du_jour(sim.t) < heure):
            sim.pas(10)
            campus.t = sim.t
            n += 1
            if n % 6 == 0:
                campus.piloter()
                campus.synchroniser(force=True)

    jouer(4, 23.9)                         # une semaine de cours : les salles apprennent leur débit d'air

    # Le lundi suivant, toutes les salles de TD assez grandes sont prises à 10 h 30 ; SAR 109 par un petit groupe
    lundi = datetime.fromordinal(debut.toordinal() + 7).date()
    physique = next(c for c in campus.planning.cours_du_jour(lundi) if c['id'] == 's12')
    occupants = {'SAR 109': 5, 'SAR 118': 24, 'SAR 120': 24, 'SAR 221': 40}   # SAR 109 : un tutorat de 5
    for k, (sid, effectif) in enumerate(occupants.items()):
        if libre(campus.planning.cours_du_jour(lundi), sid, physique['debut'], physique['fin']):
            campus.edt['cours'].append({'id': f'essai{k}', 'jour': 0, 'debut': physique['debut'], 'fin': physique['fin'],
                                        'matiere': 'Projet (essai)', 'groupes': [f'Groupe essai {k}'], 'cles': [f'E{k}'],
                                        'effectif': effectif, 'enseignant': '—', 'salle': sid, 'reel': False})
    campus.planning.cache.clear()
    campus.ajouter_cartes(sim.annuaire())  # les cartes des groupes d'essai

    jouer(7, 7.84)                         # lundi 7 h 50
    p = next((x for x in campus.previsions(frais=True)['propositions'] if x['cours'] == 's12'), None)
    print(f'Physique : {p["etudiants"]} étudiants attendus pour {p["places"]} places en {p["salle"]}' if p else 'pas de proposition')
    for r in (p['negociation'] if p else []):
        print(f'  {r["salle"]:12} {r["reponse"]:20} {r.get("detail", "")}')
    e = p and p.get('echange')
    if e:
        print(f'Échange proposé : {e["matiere"]} ({e["etudiants"]} étudiants) {e["salle"]} -> {e["vers"]}, '
              f'air {e["pic_avant"]} -> {e["pic_apres"]} ppm ; Physique en {p["proposee"]} : {p["pic_propose"]} ppm')
    verifs.append(('aucune salle libre : SAR 109 propose un échange', bool(e) and p['proposee'] == 'SAR 109' and e['vers'] == 'SAR 101'))
    reponses = {r['salle']: r['reponse'] for r in (p['negociation'] if p else [])}
    verifs.append(('chaque salle a répondu (trop petite, occupée…)', reponses.get('SAR 103') == 'trop petite'
                   and reponses.get('SAR 118') == 'occupée' and reponses.get('SAR 221') == 'occupée'))

    if e:
        campus.planning.changer_salle(lundi, 's12', p['proposee'], 'test', campus.t)
        campus.planning.changer_salle(lundi, e['cours'], e['vers'], 'test', campus.t)
        jouer(7, 13.0)
        s1 = campus.registre.seance(f'{lundi.isoformat()}_s12')
        s2 = campus.registre.seance(f'{lundi.isoformat()}_{e["cours"]}')
        badges = {s['salle']: s['presents'] + s['retards'] for s in (s1, s2) if s}
        print(f'Après l\'échange : {badges}')
        verifs.append(('Physique a eu lieu en SAR 109, le petit groupe en SAR 101',
                       s1 and s2 and s1['salle'] == 'SAR 109' and s2['salle'] == 'SAR 101'))
        verifs.append(('chacun avait une place', s1 and s2 and badges['SAR 109'] <= 29 and badges['SAR 101'] <= 19))

    print()
    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
