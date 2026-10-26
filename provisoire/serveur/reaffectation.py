"""Réaffectation intelligente des salles : le jumeau propose de déplacer un cours quand l'air de sa
salle sera mauvais, vers une salle libre où il restera bon.

Pour chaque cours qui commence dans les 4 prochaines heures (et pas avant 15 min), on prévoit le pic
de CO2 dans sa salle. S'il dépasse 1200 ppm, on simule le même cours dans chaque salle libre du même
type (TD, TP, informatique) assez grande, avec ce qui s'y passera avant, et on propose la meilleure.
Le directeur des études accepte ou ignore : rien ne bouge sans lui.

On ne propose que des salles dont le jumeau a déjà MESURÉ le débit d'air : en essai, une salle encore
inconnue (débit supposé) a donné 1700 ppm au lieu des 1000 prévus.
"""

from datetime import datetime

SEUIL = 1200                # ppm : pic prévu qui déclenche une recherche
GAIN_MINIMUM = 250          # ppm : on ne propose que si l'air est nettement meilleur ailleurs
DANS_LES = 4                # h
PAS_AVANT = 0.25            # h : un cours qui commence dans moins de 15 min n'est plus déplacé
MARGE = 0.25                # h : une salle doit être libre 15 min avant et après


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
    a_verifier = [c for c in cours_du_jour if h0 + PAS_AVANT < c['debut'] < h0 + DANS_LES and c['id'] not in ignorees]
    if not a_verifier:
        return resultat
    minutes = int((max(c['fin'] for c in a_verifier) - h0) * 60) + 5
    prevues = {sid: campus.prevision.prevoir(sid, t, minutes) for sid in salles}
    for c in a_verifier:
        pic = pic_pendant(prevues[c['salle']], c['debut'], c['fin'])
        if pic is None or pic < SEUIL:
            continue
        attendus = campus.prevision.attendus(c, jour)
        meilleure = None
        for sid, s in salles.items():
            if sid == c['salle'] or s['type'] != salles[c['salle']]['type'] or s['places'] < attendus:
                continue
            occupee = any(x['salle'] == sid and x['debut'] - MARGE < c['fin'] and x['fin'] + MARGE > c['debut']
                          for x in cours_du_jour)
            if occupee:
                continue
            p = campus.prevision.prevoir(sid, t, minutes, cours_en_plus=[{**c, 'salle': sid}])
            if p is None or p['source_debit'] == 'a priori':
                continue                                   # ventilation pas encore mesurée : on ne parie pas dessus
            pic_ailleurs = pic_pendant(p, c['debut'], c['fin'])
            if pic_ailleurs is not None and (meilleure is None or pic_ailleurs < meilleure[1]):
                meilleure = (sid, pic_ailleurs)
        if meilleure and pic - meilleure[1] >= GAIN_MINIMUM and meilleure[1] < SEUIL:
            resultat.append({
                'cours': c['id'], 'matiere': c['matiere'], 'groupes': c['groupes'], 'enseignant': c['enseignant'],
                'debut': c['debut'], 'fin': c['fin'], 'personnes': attendus,
                'salle': c['salle'], 'pic': round(pic),
                'proposee': meilleure[0], 'pic_propose': round(meilleure[1]),
                'reel': c['reel'],
            })
    return resultat
