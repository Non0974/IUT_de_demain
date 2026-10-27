"""Test du témoin CO₂ en simulation : une semaine honnête (les salles apprennent, on compte les fausses
alertes), puis le lundi suivant, dans une salle sans capteurs à la porte, un étudiant badge à chaque
cours les cartes de 6 absents. Le CO₂ doit le voir.
(Le test sur de vraies salles est dans donnees_reelles/test_temoin_co2.py.)

    python tests/test_temoin.py
"""

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import serveur     # noqa: E402
from registre import Registre  # noqa: E402
from salle import heure_du_jour  # noqa: E402
from suivi import Suivi        # noqa: E402

DIRECTEUR = {'login': 'directeur', 'role': 'directeur', 'nom': 'Directeur', 'enseignant': None}


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

    def jouer(jusqu_au_jour, heure=24.0):
        """Joue jusqu'au début du jour demandé (ou jusqu'à une heure de la veille)."""
        n = 0
        while (datetime.fromtimestamp(sim.t).date() - debut).days < jusqu_au_jour - 1 or (
                (datetime.fromtimestamp(sim.t).date() - debut).days == jusqu_au_jour - 1 and heure_du_jour(sim.t) < heure):
            sim.pas(10)
            campus.t = sim.t
            n += 1
            if n % 6 == 0:
                campus.piloter()
                campus.synchroniser(force=True)

    # 1. Une semaine honnête
    jouer(7)
    avis = {}
    for k in range(7):
        jour = debut.toordinal() + k
        for x in campus.registre.temoins_du_jour(datetime.fromordinal(jour).date()):
            avis[x['seance']] = x
    verdicts = Counter(x['verdict'] for x in avis.values())
    jugees = [x for x in avis.values() if x['verdict'] in ('coherent', 'badges_en_trop', 'personnes_sans_badge')]
    fausses = [x for x in jugees if x['verdict'] != 'coherent']
    print(f'Semaine honnête : {dict(verdicts)}')
    print(f'  {len(jugees)} cours jugés, {len(fausses)} fausses alertes')
    for x in fausses[:3]:
        print(f'    {x["salle"]} {x["matiere"]} : {x["badges"]} badges, {x["personnes"]} personnes selon le CO₂ ({x["verdict"]})')
    verifs.append(('les salles apprennent puis jugent les cours', len(jugees) >= 20))
    verifs.append(('semaine honnête : au plus 10 % de fausses alertes', len(fausses) <= 0.1 * len(jugees)))

    # 2. Le lundi suivant : 6 cartes badgées pour des absents à chaque cours d'une salle sans capteurs à la porte
    lundi = datetime.fromordinal(debut.toordinal() + 7).date()
    recalees = {sid for sid, r in campus.temoin.recalage.items() if len(r) >= 5}
    cours_lundi = campus.planning.cours_du_jour(lundi)
    candidates = [s for s in campus.batiment['salles'] if not s['equipee'] and s['id'] in recalees
                  and any(c['salle'] == s['id'] and c['effectif'] >= 15 for c in cours_lundi)]
    salle = max(candidates, key=lambda s: len(campus.temoin.recalage[s['id']]))['id']
    sim.salles[salle].pannes['cartesPretees'] = True
    jouer(8, heure=18.5)                   # lundi 18 h 30 : les cours de la salle sont finis
    lundi_avis = [x for x in campus.registre.temoins_du_jour(lundi) if x['salle'] == salle]
    print(f'Lundi, {salle}, 6 cartes badgées pour des absents à chaque cours :')
    for x in lundi_avis:
        print(f'  {x["matiere"]} : {x["badges"]} badges, {x["personnes"]} personnes selon le CO₂ '
              f'(entre {x["mini"]} et {x["maxi"]}) -> {x["verdict"]}')
    reperes = [x for x in lundi_avis if x['verdict'] == 'badges_en_trop']
    verifs.append(('cartes badgées pour 6 absents repérées par le CO₂', lundi_avis and len(reperes) == len(lundi_avis)))
    verifs.append(('écart badges / CO₂ proche de 6', reperes and all(3 <= x['badges'] - x['personnes'] <= 10 for x in reperes)))

    # 3. Ce que voient le directeur et la fiche de la séance
    campus.t = sim.t
    tableau = Suivi(campus).tableau(DIRECTEUR)
    verifs.append(('alerte dans le tableau de bord', any(a.get('temoin') and a['salle'] == salle for a in tableau['alertes'])))
    fiche = Suivi(campus).seance(DIRECTEUR, reperes[0]['seance']) if reperes else {}
    verifs.append(('avis du CO₂ sur la fiche de la séance', fiche.get('temoin', {}).get('verdict') == 'badges_en_trop'))

    print()
    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
