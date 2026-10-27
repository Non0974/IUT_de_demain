"""Réaffectation intelligente des salles : le jumeau propose de déplacer un cours vers une salle libre
quand sa salle ne convient pas :
  - air : le pic de CO2 prévu dépasse 1200 ppm (cours qui commencent dans les 4 prochaines heures) ;
  - trop petite : plus d'étudiants attendus que de places (tous les cours qui restent dans la journée).
Les salles négocient : la salle qui a un problème interroge chaque salle du même type (TD, TP,
informatique), et chacune répond avec ses propres données : libre (avec l'air qu'elle aurait avec ce
cours), trop petite, ventilation inconnue, ou occupée. Une salle occupée peut proposer un échange : son
cours irait dans la salle qui a le problème, si son groupe y tient et que l'air reste correct des deux
côtés. On garde la meilleure salle libre, sinon le meilleur échange. Le directeur des études voit la
négociation, accepte ou ignore : rien ne bouge sans lui. Sans solution, le problème est quand même signalé.

On ne propose que des salles dont le jumeau a déjà MESURÉ le débit d'air : en essai, une salle encore
inconnue (débit supposé) a donné 1700 ppm au lieu des 1000 prévus.
"""

from datetime import datetime

from capacite import MARGE, libre
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
    # Places qui restent : moins les tables ou chaises manquantes signalées (tickets pas résolus)
    salles = {s['id']: {**s, 'places': campus.places_restantes(s['id'])} for s in campus.batiment['salles']}
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
        meilleure, echange, reponses = None, None, []
        for sid, s in salles.items():
            if sid == c['salle'] or s['type'] != salles[c['salle']]['type']:
                continue
            reponse = repondre(campus, t, jour, h0, minutes, cours_du_jour, prises, prevues, c, etudiants, pic, motifs, s)
            reponses.append({k: v for k, v in reponse.items() if k in ('salle', 'reponse', 'detail')})
            if reponse['reponse'] == 'libre':
                # D'abord une salle où l'air reste bon, puis la plus petite qui suffit (on garde les grandes salles
                # pour les grands groupes), puis le meilleur air
                tri = (reponse['pic'] >= BON_AIR, s['places'], reponse['pic'])
                if meilleure is None or tri < meilleure[0]:
                    meilleure = (tri, sid, reponse['pic'])
            elif reponse['reponse'] == 'échange possible':
                tri = (reponse['pic'] >= BON_AIR, reponse['echange']['pic_apres'] >= BON_AIR, s['places'], reponse['pic'])
                if echange is None or tri < echange[0]:
                    echange = (tri, sid, reponse['pic'], reponse['echange'])
        if meilleure is None and echange is not None:
            meilleure, echange = echange[:3], echange[3]
        else:
            echange = None
        if meilleure is None and motifs == ['air']:
            continue                                       # pas mieux ailleurs : rien à proposer
        if meilleure:
            prises.append((meilleure[1], c['debut'], c['fin']))
        if echange:
            prises.append((c['salle'], echange['debut'], echange['fin']))
        resultat.append({
            'cours': c['id'], 'matiere': c['matiere'], 'groupes': c['groupes'], 'enseignant': c['enseignant'],
            'debut': c['debut'], 'fin': c['fin'], 'motifs': motifs,
            'personnes': etudiants + 1, 'etudiants': etudiants, 'inscrits': c['effectif'],
            'salle': c['salle'], 'places': places, 'places_perdues': campus.perdues.get(c['salle'], 0), 'pic': round(pic) if pic is not None else None,
            'proposee': meilleure[1] if meilleure else None,
            'places_proposee': salles[meilleure[1]]['places'] if meilleure else None,
            'pic_propose': round(meilleure[2]) if meilleure else None,
            'echange': echange,
            'negociation': sorted(reponses, key=lambda r: ORDRE_REPONSES.index(r['reponse'])),
            'reel': c['reel'],
        })
    return resultat


ORDRE_REPONSES = ('libre', 'échange possible', 'libre, air mauvais', 'occupée', 'trop petite', 'ventilation inconnue')


def repondre(campus, t, jour, h0, minutes, cours_du_jour, prises, prevues, c, etudiants, pic, motifs, s):
    """La réponse d'une salle à la demande du cours c : elle la calcule avec ses propres données."""
    sid = s['id']
    if s['places'] < etudiants:
        return {'salle': sid, 'reponse': 'trop petite', 'detail': f'{s["places"]} places'}
    if prevues[sid] is None or prevues[sid]['source_debit'] == 'a priori':
        return {'salle': sid, 'reponse': 'ventilation inconnue', 'detail': 'débit d\'air pas encore mesuré'}
    reservee = any(x == sid and d < c['fin'] and f > c['debut'] for x, d, f in prises)
    occupants = [x for x in cours_du_jour if x['salle'] == sid and x['debut'] - MARGE < c['fin'] and x['fin'] + MARGE > c['debut']]
    if not occupants and not reservee:
        p = campus.prevision.prevoir(sid, t, minutes, cours_en_plus=[{**c, 'salle': sid}])
        pic_ici = pic_pendant(p, c['debut'], c['fin'])
        if pic_ici is None or pic_ici >= SEUIL or (motifs == ['air'] and pic - pic_ici < GAIN_MINIMUM):
            return {'salle': sid, 'reponse': 'libre, air mauvais', 'detail': f'{round(pic_ici or 0)} ppm prévus avec ce cours'}
        return {'salle': sid, 'reponse': 'libre', 'pic': pic_ici, 'detail': f'{round(pic_ici)} ppm prévus avec ce cours'}
    if reservee or len(occupants) != 1:
        return {'salle': sid, 'reponse': 'occupée', 'detail': 'déjà promise à un autre cours' if reservee else 'plusieurs cours'}
    # Une seule salle occupée par un seul cours : elle propose un échange si c'est possible
    autre = occupants[0]
    if autre['debut'] <= h0 + PAS_AVANT:
        return {'salle': sid, 'reponse': 'occupée', 'detail': f'{autre["matiere"]} a déjà commencé'}
    autres = campus.prevision.etudiants_attendus(autre, jour)
    if autres > campus.places_restantes(c['salle']):
        return {'salle': sid, 'reponse': 'occupée', 'detail': f'{autre["matiere"]} ({autres} étudiants) ne tiendrait pas en {c["salle"]}'}
    if not libre([x for x in cours_du_jour if x['id'] != c['id']], c['salle'], autre['debut'], autre['fin']):
        return {'salle': sid, 'reponse': 'occupée', 'detail': f'{c["salle"]} n\'est pas libre pendant {autre["matiere"]}'}
    duree = int((max(c['fin'], autre['fin']) - h0) * 60) + 5
    pour_moi = campus.prevision.prevoir(sid, t, duree, cours_en_plus=[{**c, 'salle': sid}], sans_cours=[autre['id']])
    pour_lui = campus.prevision.prevoir(c['salle'], t, duree, cours_en_plus=[{**autre, 'salle': c['salle']}], sans_cours=[c['id']])
    pic_moi = pic_pendant(pour_moi, c['debut'], c['fin'])
    pic_lui = pic_pendant(pour_lui, autre['debut'], autre['fin'])
    pic_lui_avant = pic_pendant(campus.prevision.prevoir(sid, t, duree), autre['debut'], autre['fin'])
    if pic_moi is None or pic_lui is None or pic_moi >= SEUIL or pic_lui >= SEUIL or (
            motifs == ['air'] and pic - pic_moi < GAIN_MINIMUM):
        return {'salle': sid, 'reponse': 'occupée', 'detail': f'échanger avec {autre["matiere"]} rendrait l\'air mauvais'}
    return {'salle': sid, 'reponse': 'échange possible', 'pic': pic_moi,
            'detail': f'son cours de {autre["matiere"]} ({autres} étudiants) irait en {c["salle"]}',
            'echange': {'cours': autre['id'], 'matiere': autre['matiere'], 'groupes': autre['groupes'],
                        'enseignant': autre['enseignant'], 'debut': autre['debut'], 'fin': autre['fin'],
                        'etudiants': autres, 'salle': sid, 'vers': c['salle'],
                        'pic_avant': round(pic_lui_avant) if pic_lui_avant is not None else None, 'pic_apres': round(pic_lui)}}


def texte_proposition(x):
    """Une phrase pour les alertes du tableau de bord."""
    raisons = []
    if 'air' in x['motifs']:
        raisons.append(f'{x["pic"]} ppm prévus')
    if 'trop_petite' in x['motifs']:
        perdues = f', {x["places_perdues"]} en moins : matériel manquant' if x.get('places_perdues') else ''
        raisons.append(f'{x["etudiants"]} étudiants attendus pour {x["places"]} places{perdues}')
    cours = f'{x["matiere"]} ({x["groupes"][0]}, {heure_texte(x["debut"])})'
    if x['proposee'] is None:
        return f'{cours} en {x["salle"]} : {" et ".join(raisons)}. Aucune salle libre assez grande, aucun échange possible.'
    if x.get('echange'):
        e = x['echange']
        return (f'Proposition : échanger les salles de {cours} ({x["salle"]}) et de {e["matiere"]} ({e["salle"]}), '
                f'{" et ".join(raisons)}.')
    return f'Proposition : déplacer {cours} de {x["salle"]} à {x["proposee"]} ({" et ".join(raisons)}).'
