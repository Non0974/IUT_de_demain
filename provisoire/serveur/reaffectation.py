"""Réaffectation intelligente des salles : le jumeau propose de déplacer un cours vers une salle libre
quand sa salle ne convient pas :
  - air : le pic de CO2 prévu dépasse 1200 ppm (cours qui commencent dans les 4 prochaines heures) ;
  - trop petite : plus d'étudiants attendus que de places (tous les cours qui restent dans la journée).
On simule le cours dans chaque salle libre du même type (TD, TP, informatique) avec assez de places, avec
ce qui s'y passera avant, et on propose la meilleure. Le directeur des études accepte ou ignore : rien
ne bouge sans lui. Sans salle libre assez grande, le problème est quand même signalé.

On ne propose que des salles dont le jumeau a déjà MESURÉ le débit d'air : en essai, une salle encore
inconnue (débit supposé) a donné 1700 ppm au lieu des 1000 prévus.
"""

from datetime import datetime

from capacite import libre
from registre import heure_texte

SEUIL = 1200                # ppm : pic prévu qui déclenche une recherche
BON_AIR = 1000              # ppm : sous ce pic, l'air de la salle proposée est bon
GAIN_MINIMUM = 250          # ppm : pour l'air seul, on ne propose que si l'air est nettement meilleur ailleurs
DANS_LES = 4                # h : horizon des prévisions d'air
PAS_AVANT = 0.25            # h : un cours qui commence dans moins de 15 min n'est plus déplacé


def pic_pendant(prevision, debut, fin):
    """Pic de CO2 prévu pendant un cours (prévision minute par minute)."""
    if prevision is None:
        return None
    h0 = prevision['heure']
    valeurs = [c for k, c in enumerate(prevision['co2']) if debut <= h0 + k / 60 <= fin]
    return max(valeurs) if valeurs else None


def propositions(campus, t):
    jour = datetime.fromtimestamp(t).date()
    h0 = datetime.fromtimestamp(t).hour + datetime.fromtimestamp(t).minute / 60
    cours_du_jour = [c for c in campus.planning.cours_du_jour(jour) if c['salle']]
    ignorees = campus.registre.propositions_ignorees(jour)
    salles = {s['id']: s for s in campus.batiment['salles']}
    resultat = []
    a_verifier = sorted((c for c in cours_du_jour if h0 + PAS_AVANT < c['debut'] and c['id'] not in ignorees),
                        key=lambda c: c['debut'])
    if not a_verifier:
        return resultat
    minutes = int((max(c['fin'] for c in a_verifier) - h0) * 60) + 5
    prevues = {sid: campus.prevision.prevoir(sid, t, minutes) for sid in salles}
    prises = []                                       # salles déjà proposées à un autre cours
    for c in a_verifier:
        etudiants = campus.prevision.etudiants_attendus(c, jour)
        places = salles[c['salle']]['places']
        pic = pic_pendant(prevues[c['salle']], c['debut'], c['fin'])
        motifs = []
        if c['debut'] < h0 + DANS_LES and pic is not None and pic >= SEUIL:
            motifs.append('air')
        if etudiants > places:
            motifs.append('trop_petite')
        if not motifs:
            continue
        meilleure = None
        for sid, s in salles.items():
            if sid == c['salle'] or s['type'] != salles[c['salle']]['type'] or s['places'] < etudiants:
                continue
            if not libre(cours_du_jour, sid, c['debut'], c['fin']) or any(
                    x == sid and d < c['fin'] and f > c['debut'] for x, d, f in prises):
                continue
            p = campus.prevision.prevoir(sid, t, minutes, cours_en_plus=[{**c, 'salle': sid}])
            if p is None or p['source_debit'] == 'a priori':
                continue                                   # ventilation pas encore mesurée : on ne parie pas dessus
            pic_ailleurs = pic_pendant(p, c['debut'], c['fin'])
            if pic_ailleurs is None or pic_ailleurs >= SEUIL:
                continue
            if motifs == ['air'] and pic - pic_ailleurs < GAIN_MINIMUM:
                continue
            # D'abord une salle où l'air reste bon, puis la plus petite qui suffit (on garde les grandes salles
            # pour les grands groupes), puis le meilleur air
            tri = (pic_ailleurs >= BON_AIR, s['places'], pic_ailleurs)
            if meilleure is None or tri < meilleure[0]:
                meilleure = (tri, sid, pic_ailleurs)
        if meilleure is None and motifs == ['air']:
            continue                                       # pas mieux ailleurs : rien à proposer
        if meilleure:
            prises.append((meilleure[1], c['debut'], c['fin']))
        resultat.append({
            'cours': c['id'], 'matiere': c['matiere'], 'groupes': c['groupes'], 'enseignant': c['enseignant'],
            'debut': c['debut'], 'fin': c['fin'], 'motifs': motifs,
            'personnes': etudiants + 1, 'etudiants': etudiants, 'inscrits': c['effectif'],
            'salle': c['salle'], 'places': places, 'pic': round(pic) if pic is not None else None,
            'proposee': meilleure[1] if meilleure else None,
            'places_proposee': salles[meilleure[1]]['places'] if meilleure else None,
            'pic_propose': round(meilleure[2]) if meilleure else None,
            'reel': c['reel'],
        })
    return resultat


def texte_proposition(x):
    """Une phrase pour les alertes du tableau de bord."""
    raisons = []
    if 'air' in x['motifs']:
        raisons.append(f'{x["pic"]} ppm prévus')
    if 'trop_petite' in x['motifs']:
        raisons.append(f'{x["etudiants"]} étudiants attendus pour {x["places"]} places')
    cours = f'{x["matiere"]} ({x["groupes"][0]}, {heure_texte(x["debut"])})'
    if x['proposee'] is None:
        return f'{cours} en {x["salle"]} : {" et ".join(raisons)}. Aucune salle libre assez grande.'
    return f'Proposition : déplacer {cours} de {x["salle"]} à {x["proposee"]} ({" et ".join(raisons)}).'
