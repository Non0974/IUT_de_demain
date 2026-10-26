"""Test du jumeau prédictif : précision des prévisions, ventilation anticipée, réaffectation des salles.

Une semaine simulée deux fois sur la salle de l'automate (SAR 200) :
  - avec la règle simple d'avant (ventilation selon le nombre de personnes) ;
  - avec la commande prédictive du jumeau.
On compare l'énergie et les minutes de mauvais air vraiment simulées. Puis on accepte une
proposition de changement de salle (le cours trop gros pour sa salle) et on vérifie que le cours a bien
eu lieu ailleurs, avec une place pour chacun et un meilleur air que prévu dans sa salle d'origine.
On vérifie aussi ce que le jumeau a appris sur la présence de chaque groupe, l'écart entre les
étudiants prévus le matin et ceux venus, et que l'alerte « plus de monde que de places » ne se
trompe jamais.

    python tests/test_prevision.py
"""

import sys
from datetime import datetime, timedelta
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


TROP_PLEIN = 'Plus de monde que de places'


def main():
    verifs = []

    # Alerte « plus de monde que de places » : toutes les 5 min de cours, dans chaque salle. On note aussi
    # combien de personnes y étaient vraiment (simulation), pour repérer les fausses alertes.
    alertes = []

    def surveiller(campus, sim):
        d = datetime.fromtimestamp(campus.t)
        if d.minute % 5 or not 8 <= d.hour < 18:
            return
        for sid, salle in campus.salles.items():
            if any(a['texte'].startswith(TROP_PLEIN) for a in salle.etat(campus.t)['alertes']):
                alertes.append((d.weekday(), heure_du_jour(campus.t), sid, salle.salle['places'], sim.salles[sid].n_reel))

    regle, vrai_regle = semaine('reactive', avant_chaque_minute=surveiller)
    jumeau, vrai_jumeau = semaine('predictive')
    print('Salle SAR 200, une semaine simulée (vrai CO2 de la simulation) :')
    for nom, v in (('règle simple', vrai_regle), ('jumeau prédictif', vrai_jumeau)):
        print(f'  {nom:17} {v["energie"]:6.1f} kWh   {v["minutes_1000"]:4d} min > 1000 ppm   {v["minutes_800"]:4d} min > 800 ppm')
    economie = 1 - vrai_jumeau['energie'] / vrai_regle['energie']
    print(f'  économie d\'énergie : {economie:.0%}')
    verifs.append(('le jumeau dépense moins d\'énergie que la règle simple', economie > 0.05))
    verifs.append(('sans plus de minutes au-dessus de 1000 ppm',
                   vrai_jumeau['minutes_1000'] <= vrai_regle['minutes_1000'] + 10))

    fausses = [a for a in alertes if a[4] <= a[3] + 1]           # pas plus de monde que places + enseignant
    print(f'Alertes « plus de monde que de places » (semaine sans changement de salle) : {len(alertes)}, '
          f'dont {len(fausses)} dans une salle qui ne débordait pas')
    for jour, h, sid, places, vraies in alertes[:2] + fausses:
        print(f'  jour {jour} {h:.2f} h  {sid} : {vraies} personnes pour {places} places')
    verifs.append(('alerte « plus de monde que de places » : jamais à tort', not fausses))

    p = jumeau.prevision.precision()
    print(f'Précision des prévisions (toutes salles) : {p}')
    verifs.append(('erreur moyenne à 30 min < 120 ppm', p['30 min']['erreur_moyenne'] is not None and p['30 min']['erreur_moyenne'] < 120))
    verifs.append(('erreur moyenne à 60 min < 180 ppm', p['60 min']['erreur_moyenne'] is not None and p['60 min']['erreur_moyenne'] < 180))

    # Réaffectation : après une semaine d'apprentissage (les salles connaissent leur débit), le lundi
    # suivant à 7 h 50, on accepte la première proposition et on regarde ce qui se passe
    acceptee = {}
    matins = {}                                      # ce que le jumeau prévoyait à 7 h 50 : jeudi, vendredi, lundi suivant
    debut_test = datetime.fromtimestamp(serveur.charger_simulateur('batiment').DEBUT_SEMAINE.timestamp()).date()

    def regarder(campus, sim):
        d = datetime.fromtimestamp(campus.t)
        jour = (d.date() - debut_test).days
        if jour not in (3, 4, 7) or jour in matins or d.hour != 7 or d.minute != 50:
            return
        p = campus.previsions()
        appris = campus.prevision.appris(d.date())
        matins[jour] = {'appris': appris, 'prevus': {c['cours']: (c['prevus'], round(c['inscrits'] * appris['moyen']))
                                                      for s in p['capacite']['salles'] for c in s['cours']}}
        if jour != 7:
            return
        props = p['propositions']
        print(f'Lundi suivant, 7 h 50 : {len(props)} proposition(s)')
        for x in props:
            print(f'  {x["matiere"]} ({x["groupes"][0]}) {x["salle"]} -> {x["proposee"]} [{", ".join(x["motifs"])}] : '
                  f'{x["etudiants"]} étudiants pour {x["places"]} places, pic prévu {x["pic"]} -> {x["pic_propose"]} ppm')
        x = next((x for x in props if 'trop_petite' in x['motifs']), props[0] if props else None)
        if x and x['proposee']:
            campus.planning.changer_salle(d.date(), x['cours'], x['proposee'], 'test', campus.t)
            acceptee.update(x, jour=d.date())

    campus, _ = semaine('predictive', jours=8, avant_chaque_minute=regarder)

    # Ce que le jumeau a appris sur la présence (dans la simulation : TP1 manque plus que TP2, et tout le
    # monde manque plus le vendredi après-midi)
    # Le taux d'un groupe suit ce qui a été observé (une semaine de données : le hasard pèse encore, par
    # exemple TP1 est venu à 95 % la semaine du 16 novembre alors que la simulation le fait venir à 82 %).
    a = matins[7]['appris']
    vendredi = a['creneaux'].get((4, 'après-midi'), 1.0)
    simu = serveur.charger_simulateur('batiment')
    print(f'Présence apprise : moyenne {a["moyen"]:.0%}, vendredi après-midi {vendredi - 1:+.0%}')
    for g in ('TP1', 'TP2'):
        print(f'  {g} : appris {a["groupes"][g]:.0%} (sur {a["presences"][g]} présences ; '
              f'la simulation le fait venir à {1 - simu.part_absents(g, simu.DEBUT_SEMAINE, 9):.0%})')
    verifs.append(('appris : moins de présents le vendredi après-midi', vendredi < 0.97))

    # Places : étudiants prévus à 7 h 50 contre étudiants badgés, à chaque cours de ces trois journées
    ecarts = []
    for jour, m in matins.items():
        reels_jour = {s['cours']: s['presents'] + s['retards'] + s['a_verifier']
                      for s in campus.registre.seances_du_jour(debut_test + timedelta(days=jour))}
        ecarts += [(abs(prevu - reels_jour[k]), abs(naif - reels_jour[k])) for k, (prevu, naif) in m['prevus'].items()
                   if k in reels_jour]
        if jour == 7:
            reels = reels_jour
    jumeau_moy = sum(e for e, _ in ecarts) / len(ecarts)
    naif_moy = sum(n for _, n in ecarts) / len(ecarts)
    print(f'Places, {len(ecarts)} cours (jeudi, vendredi, lundi) : écart moyen prévu / badgés {jumeau_moy:.2f} étudiant '
          f'(effectif × taux moyen : {naif_moy:.2f})')
    verifs.append(('étudiants prévus le matin à 2,5 près en moyenne', jumeau_moy <= 2.5))
    verifs.append(('apprendre chaque groupe ne fait pas pire que le taux moyen', jumeau_moy <= naif_moy + 0.2))

    verifs.append(('salle trop petite repérée le matin (Physique : 28 inscrits, 19 places)',
                   bool(acceptee) and 'trop_petite' in acceptee['motifs']))
    if acceptee:
        sid = f'{acceptee["jour"].isoformat()}_{acceptee["cours"]}'
        s = campus.registre.seance(sid)
        verifs.append(('le cours a bien eu lieu dans la salle proposée', s is not None and s['salle'] == acceptee['proposee']))
        venus = reels.get(acceptee['cours'])
        print(f'  {acceptee["matiere"]} en {acceptee["proposee"]} : {venus} étudiants badgés pour {acceptee["places_proposee"]} places '
              f'({acceptee["places"]} dans l\'ancienne salle, {acceptee["etudiants"]} prévus)')
        verifs.append(('tout le monde avait une place dans la nouvelle salle', venus is not None and venus <= acceptee['places_proposee']))
        debut, fin = acceptee['debut'], acceptee['fin']
        mesures = [c for t, c, _ in campus.salles[acceptee['proposee']].historique
                   if datetime.fromtimestamp(t).date() == acceptee['jour'] and debut <= heure_du_jour(t) <= fin]
        print(f'  pic mesuré dans la nouvelle salle : {max(mesures):.0f} ppm (prévu {acceptee["pic_propose"]}, '
              f'{acceptee["pic"]} prévus dans l\'ancienne)' if mesures else '  pas de mesure')
        if acceptee['pic'] is not None:
            verifs.append(('l\'air y est resté meilleur que prévu dans l\'ancienne salle', bool(mesures) and max(mesures) < acceptee['pic'] - 150))

    print()
    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
