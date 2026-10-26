"""Capacité des salles : chaque cours de la journée face aux places de sa salle.

  - cours commencé depuis 15 min, ou fini : le nombre d'étudiants vraiment là. Dans une salle avec
    capteurs à la porte, le comptage (le plus haut pendant le cours, enseignant retiré) : il voit aussi
    ceux qui n'ont pas badgé. Ailleurs, les badges du registre : le Wi-Fi se trompe de 2 ou 3 personnes ;
  - cours à venir : le nombre prévu par le jumeau, avec le taux de présence qu'il a appris pour chaque
    groupe et chaque demi-journée de la semaine (prevision.py).
Chaque cours est classé : salle trop petite (plus d'étudiants que de places), pleine (plus de 90 %),
adaptée, ou trop grande (moins de 40 % et au moins 10 places vides, alors que le bâtiment a une salle
du même type plus petite d'au moins 6 places où le groupe tient). Un demi-groupe de TP dans une salle de
TP n'est donc pas « trop grand » : il n'y a pas plus petit. Pour une salle trop grande, on nomme la plus
petite de ces salles qui est libre au même moment.
Un cours à venir dans une salle trop petite donne une proposition de changement (reaffectation.py).
"""

from datetime import datetime

from salle import heure_du_jour

PLEINE = 0.9
TROP_GRANDE = 0.4
PLACES_VIDES = 10           # places vides au moins, pour dire qu'une salle est trop grande
REMPLISSAGE_VISE = 0.85     # une salle plus petite qu'on nomme reste remplie à 85 % au plus
GAIN_PLACES = 6             # et libère au moins 6 places
MESURE_APRES = 15 / 60      # h : on prend le comptage 15 min après le début, quand tout le monde est là
JOURNEE = (8.0, 18.0)       # h : créneaux comptés dans le taux d'occupation des salles
MARGE = 0.25                # h : une salle doit être libre 15 min avant et après un cours


def etat(etudiants, places):
    if etudiants > places:
        return 'trop_petite'
    if etudiants > PLEINE * places:
        return 'pleine'
    if etudiants < TROP_GRANDE * places and places - etudiants >= PLACES_VIDES:
        return 'trop_grande'
    return 'adaptee'


def libre(cours_du_jour, salle, debut, fin, sauf=None):
    """La salle n'a pas d'autre cours de debut - 15 min à fin + 15 min."""
    return not any(x['salle'] == salle and x['id'] != sauf and x['debut'] - MARGE < fin and x['fin'] + MARGE > debut
                   for x in cours_du_jour)


def capacite(campus, t):
    jour = datetime.fromtimestamp(t).date()
    h = heure_du_jour(t)
    cours = [c for c in campus.planning.cours_du_jour(jour) if c['salle']]
    batiment = campus.batiment['salles']
    badges = {x['cours']: x['presents'] + x['retards'] + x['a_verifier'] for x in campus.registre.seances_du_jour(jour)}
    salles, tous = [], []
    for s in batiment:
        etat_salle = campus.salles[s['id']]
        historique = [(heure_du_jour(tm), n) for tm, _, n in etat_salle.historique]
        liste = []
        for c in sorted((c for c in cours if c['salle'] == s['id']), key=lambda c: c['debut']):
            prevus = campus.prevision.etudiants_attendus(c, jour)
            compte, source = None, 'prévu'
            if h >= c['debut'] + MESURE_APRES:
                vus = [n for hm, n in historique if c['debut'] + MESURE_APRES <= hm <= min(h, c['fin'])]
                if etat_salle.porte and vus:
                    compte, source = max(0, max(vus) - 1), 'porte'          # sans l'enseignant
                elif c['id'] in badges:
                    compte, source = badges[c['id']], 'badges'
            etudiants = compte if compte is not None else prevus
            e = etat(etudiants, s['places'])
            plus_petite = None
            if e == 'trop_grande':
                assez = [x for x in batiment if x['type'] == s['type']
                         and etudiants / REMPLISSAGE_VISE <= x['places'] <= s['places'] - GAIN_PLACES]
                if not assez:
                    e = 'adaptee'           # pas plus petit dans le bâtiment (demi-groupe de TP) : c'est la bonne salle
                plus_petite = min((x for x in assez if libre(cours, x['id'], c['debut'], c['fin'])),
                                  key=lambda x: x['places'], default=None)
            x = {
                'cours': c['id'], 'matiere': c['matiere'], 'groupes': c['groupes'], 'cles': c['cles'],
                'enseignant': c['enseignant'], 'debut': c['debut'], 'fin': c['fin'], 'inscrits': c['effectif'],
                'etudiants': etudiants, 'prevus': prevus, 'source': source,
                'moment': 'fini' if h > c['fin'] else 'en cours' if h >= c['debut'] else 'à venir',
                'remplissage': round(etudiants / s['places'], 3), 'etat': e, 'reel': c['reel'],
                'plus_petite': {'salle': plus_petite['id'], 'places': plus_petite['places']} if plus_petite else None,
            }
            liste.append(x)
            tous.append((x, s['places']))
        reserve = sum(max(0.0, min(c['fin'], JOURNEE[1]) - max(c['debut'], JOURNEE[0])) for c in liste)
        salles.append({'salle': s['id'], 'type': s['type'], 'libelle': s['libelle'], 'places': s['places'],
                       'cours': liste, 'occupation': round(reserve / (JOURNEE[1] - JOURNEE[0]), 3)})

    duree = [(x['fin'] - x['debut'], x['etudiants'], places) for x, places in tous]
    places_heures = sum(d * p for d, _, p in duree)
    a = campus.prevision.appris(jour)
    groupes_du_jour = sorted({cle for c in cours for cle in c['cles']})
    noms = campus.registre.noms_groupes
    return {
        'date': jour.isoformat(), 'heure': h, 'journee': JOURNEE,
        'salles': salles,
        'chiffres': {
            'remplissage_moyen': round(sum(d * e for d, e, _ in duree) / places_heures, 3) if places_heures else None,
            'occupation': round(sum(s['occupation'] for s in salles) / len(salles), 3) if salles else None,
            'places_vides_heures': round(sum(d * max(0, p - e) for d, e, p in duree)),
            **{k: sum(1 for x, _ in tous if x['etat'] == k) for k in ('trop_petite', 'pleine', 'adaptee', 'trop_grande')},
        },
        # Ce que le jumeau a appris : taux de présence des groupes du jour, effet de la demi-journée
        'appris': {
            'moyen': round(a['moyen'], 3),
            'demi_journees': {d: round(a['creneaux'].get((jour.weekday(), d), 1.0) - 1, 3) for d in ('matin', 'après-midi')},
            'groupes': [{'cle': k, 'nom': noms.get(k, k), 'taux': round(a['groupes'].get(k, a['moyen']), 3),
                         'presences': a['presences'].get(k, 0)} for k in groupes_du_jour],
        },
    }
