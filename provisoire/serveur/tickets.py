"""Tickets : il manque une table en SAR 101, plus de feutres en SAR 102, le vidéoprojecteur ne marche pas...

Un enseignant (ou la direction) signale le problème en quelques clics. Le jumeau, qui connaît l'emploi
du temps et l'occupation de chaque salle, ajoute ce qu'un simple formulaire ne sait pas :
  - l'échéance : le prochain cours dans la salle (« à faire avant 13h30 ») ;
  - l'urgence : il manque des places pour le prochain cours, ou il manque de quoi faire cours (feutres,
    vidéoprojecteur...) dans moins de 2 h ; sinon « avant le prochain cours », ou « pas pressé » si la
    salle n'a pas cours avant après-demain ;
  - le bon moment pour intervenir : la salle est libre de 12h30 à 13h30 (on ne dérange pas un cours) ;
  - les places perdues : 2 tables manquantes = 4 places de moins. Tant que le ticket est ouvert, la
    capacité et les propositions de changement de salle comptent avec les places qui restent.
Le jumeau ouvre aussi lui-même un ticket quand il détecte une panne (ventilation, capteur de CO₂, comptage).

Le service technique voit seulement les tickets, jamais les présences des étudiants.
"""

from datetime import datetime, timedelta

from registre import heure_texte
from salle import heure_du_jour

# Ce qu'on peut signaler. places : places perdues par objet manquant (une table de TD = 2 places, à
# ajuster) ; cours : il en faut pour faire cours (feutres, vidéoprojecteur...) ; quantite : on dit combien.
OBJETS = {
    'table': {'nom': 'Table', 'service': 'logistique', 'places': 2, 'quantite': True},
    'chaise': {'nom': 'Chaise', 'service': 'logistique', 'places': 1, 'quantite': True},
    'feutres': {'nom': 'Feutres', 'service': 'logistique', 'cours': True},
    'effaceur': {'nom': 'Brosse ou effaceur', 'service': 'logistique', 'cours': True},
    'videoprojecteur': {'nom': 'Vidéoprojecteur', 'service': 'informatique', 'cours': True},
    'hdmi': {'nom': 'Câble HDMI ou adaptateur', 'service': 'informatique', 'cours': True},
    'poste': {'nom': 'Poste informatique', 'service': 'informatique', 'places': 1, 'quantite': True},
    'chauffage': {'nom': 'Chauffage ou température', 'service': 'maintenance', 'cours': True},
    'eclairage': {'nom': 'Éclairage', 'service': 'maintenance', 'cours': True},
    'prise': {'nom': 'Prise électrique', 'service': 'maintenance'},
    'proprete': {'nom': 'Propreté', 'service': 'entretien'},
    'autre': {'nom': 'Autre', 'service': 'logistique'},
    # Ouverts par le jumeau seulement
    'ventilation': {'nom': 'Ventilation', 'service': 'maintenance', 'cours': True, 'jumeau': True},
    'capteur': {'nom': 'Capteur CampusTwin', 'service': 'informatique', 'jumeau': True, 'pas_presse': True},
}
SERVICES = {'logistique': 'Logistique', 'informatique': 'Informatique', 'maintenance': 'Maintenance',
            'entretien': 'Entretien'}
STATUTS = ('ouvert', 'en cours', 'résolu')
QUANTITE_MAX = 30
URGENT_AVANT = 2.0          # h : il manque de quoi faire cours pour un cours qui commence dans moins de 2 h
ARRIVEE = 0.5               # h : du monde dans la salle avant un cours = les étudiants qui arrivent
JOURS_VUS = 7               # on cherche le prochain cours de la salle sur une semaine
# Pannes que le jumeau détecte lui-même -> objet du ticket
PANNES_JUMEAU = {'ventilation': 'ventilation', 'capteur': 'capteur', 'derive': 'capteur', 'comptage': 'capteur'}


def titre(objet, quantite, detail=''):
    """« Il manque 2 tables », « Vidéoprojecteur en panne »..."""
    q = quantite or 1
    return {
        'table': f'Il manque {q} table{"s" if q > 1 else ""}',
        'chaise': f'Il manque {q} chaise{"s" if q > 1 else ""}',
        'feutres': 'Il manque des feutres',
        'effaceur': 'Il manque une brosse ou un effaceur',
        'videoprojecteur': 'Vidéoprojecteur en panne',
        'hdmi': 'Câble HDMI ou adaptateur manquant',
        'poste': f'{q} poste{"s" if q > 1 else ""} informatique{"s" if q > 1 else ""} en panne',
        'chauffage': 'Problème de chauffage',
        'eclairage': 'Éclairage en panne',
        'prise': 'Prise électrique en panne',
        'proprete': 'Salle à nettoyer',
        'ventilation': 'Ventilation en panne',
        'capteur': 'Capteur à vérifier',
    }.get(objet) or (detail[:60] if detail else 'Autre problème')


def places_perdues(objet, quantite):
    return OBJETS[objet].get('places', 0) * (quantite or 1)


def nouveau(salles, salle, objet, quantite, detail):
    """Vérifie un ticket envoyé par l'interface et le complète (service, places perdues)."""
    if salle not in salles:
        raise ValueError('Salle inconnue.')
    if objet not in OBJETS or OBJETS[objet].get('jumeau'):
        raise ValueError('Objet inconnu.')
    detail = str(detail or '').strip()[:300]
    if objet == 'autre' and not detail:
        raise ValueError('Dites ce qui ne va pas.')
    if OBJETS[objet].get('quantite'):
        try:
            quantite = int(quantite)
        except (TypeError, ValueError):
            raise ValueError('Combien ?') from None
        if not 1 <= quantite <= QUANTITE_MAX:
            raise ValueError(f'Entre 1 et {QUANTITE_MAX}.')
    else:
        quantite = None
    return {'salle': salle, 'objet': objet, 'quantite': quantite, 'detail': detail,
            'service': OBJETS[objet]['service'], 'places_perdues': places_perdues(objet, quantite)}


# ---------- ce que le jumeau ajoute ----------

def cours_a_venir(campus, salle, t):
    """Cours de la salle en ce moment (ou None) et prochain cours qui commence : (en cours, jour, cours)."""
    d0 = datetime.fromtimestamp(t).date()
    h = heure_du_jour(t)
    en_cours = next((c for c in campus.planning.cours_du_jour(d0) if c['salle'] == salle and c['debut'] <= h < c['fin']), None)
    for k in range(JOURS_VUS):
        jour = d0 + timedelta(days=k)
        suivant = min((c for c in campus.planning.cours_du_jour(jour) if c['salle'] == salle and (k or c['debut'] > h)),
                      key=lambda c: c['debut'], default=None)
        if suivant:
            return en_cours, jour, suivant
    return en_cours, None, None


def du_monde(campus, salle):
    """Du monde dans la salle : compté à la porte, ou au moins 3 personnes pour le Wi-Fi (il se trompe de ±2)."""
    s = campus.salles[salle]
    return s.nombre() >= (1 if s.porte else 3)


def creneau_libre(campus, salle, t):
    """Quand intervenir sans déranger un cours : le prochain moment où la salle est libre aujourd'hui."""
    jour = datetime.fromtimestamp(t).date()
    h = heure_du_jour(t)
    cours = sorted((c for c in campus.planning.cours_du_jour(jour) if c['salle'] == salle and c['fin'] > h),
                   key=lambda c: c['debut'])
    debut = h
    monde = du_monde(campus, salle)
    if monde and cours and h < cours[0]['debut'] <= h + ARRIVEE:
        debut = cours[0]['debut']                 # les étudiants arrivent pour le cours qui commence
    for c in cours:
        if c['debut'] > debut:
            break
        debut = max(debut, c['fin'])              # cours en cours (ou qui s'enchaînent) : on attend la fin
    suivant = next((c for c in cours if c['debut'] >= debut), None)
    fin = suivant['debut'] if suivant else None
    jusqua = f" jusqu'à {heure_texte(fin)}." if fin else " jusqu'au soir."
    if debut > h:
        texte = f'Cours en ce moment ou qui commence : salle libre à partir de {heure_texte(debut)}' + jusqua
    elif monde:
        texte = 'Du monde dans la salle en ce moment, hors cours' + (f' ; prochain cours à {heure_texte(fin)}.' if fin else '.')
    else:
        texte = "Salle libre maintenant" + jusqua
    return {'debut': debut, 'fin': fin, 'maintenant': debut <= h and not monde, 'texte': texte}


def _quand(jour, aujourd_hui, h):
    if jour == aujourd_hui:
        return f'à {heure_texte(h)}'
    return f'demain à {heure_texte(h)}' if (jour - aujourd_hui).days == 1 else f'le {jour:%d/%m} à {heure_texte(h)}'


def analyser(campus, ticket, t, perdues_salle):
    """Échéance, urgence et bon moment pour intervenir. perdues_salle : places perdues dans la salle
    (tous ses tickets ouverts)."""
    salle = ticket['salle']
    places = campus.batiment_salles[salle]['places']
    restantes = max(0, places - perdues_salle)
    aujourd_hui = datetime.fromtimestamp(t).date()
    h = heure_du_jour(t)
    a = {'places': places, 'places_restantes': restantes, 'echeance': None,
         'urgence': 'pas pressé', 'raison': "Pas de cours dans la salle d'ici une semaine.",
         'creneau': creneau_libre(campus, salle, t) if ticket['statut'] != 'résolu' else None}
    if ticket['statut'] == 'résolu':
        a['urgence'] = None
        return a
    objet = OBJETS[ticket['objet']]
    if objet.get('pas_presse'):
        a['raison'] = "Le jumeau corrige ou contourne en attendant : à vérifier quand la salle est libre."
        return a
    en_cours, jour, suivant = cours_a_venir(campus, salle, t)
    # Places : le premier cours d'aujourd'hui (en cours ou à venir) qui n'a plus assez de places
    trop = None
    if ticket['places_perdues'] > 0:
        for x in sorted((c for c in campus.planning.cours_du_jour(aujourd_hui) if c['salle'] == salle and c['fin'] > h),
                        key=lambda c: c['debut']):
            n = campus.prevision.etudiants_attendus(x, aujourd_hui)
            if n > restantes:
                trop = (x, n)
                break
    if trop:
        x, n = trop
        maintenant = x['debut'] <= h
        a['urgence'] = 'urgent'
        a['raison'] = (f'{"Cours en ce moment" if maintenant else heure_texte(x["debut"])} : {x["matiere"]}, {n} étudiants '
                       f'{"" if maintenant else "attendus "}pour {restantes} places restantes ({places} − {perdues_salle}).')
        a['echeance'] = {'date': aujourd_hui.isoformat(), 'heure': x['debut'], 'maintenant': maintenant,
                         'texte': 'tout de suite' if maintenant else heure_texte(x['debut'])}
        return a
    if objet.get('cours') and en_cours:
        a['urgence'] = 'urgent'
        a['raison'] = f"Cours en ce moment : {en_cours['matiere']}, jusqu'à {heure_texte(en_cours['fin'])}."
        a['echeance'] = {'date': aujourd_hui.isoformat(), 'heure': h, 'maintenant': True, 'texte': 'tout de suite'}
        return a
    if not suivant:
        return a
    n = campus.prevision.etudiants_attendus(suivant, jour)
    quand = _quand(jour, aujourd_hui, suivant['debut'])
    a['echeance'] = {'date': jour.isoformat(), 'heure': suivant['debut'], 'maintenant': False,
                     'texte': quand.removeprefix('à ').removeprefix('le ')}
    if objet.get('cours') and jour == aujourd_hui and suivant['debut'] - h <= URGENT_AVANT:
        a['urgence'] = 'urgent'
        a['raison'] = f'Cours {quand} : {suivant["matiere"]}, {n} étudiants attendus.'
    elif (jour - aujourd_hui).days <= 1:
        a['urgence'] = 'avant le prochain cours'
        a['raison'] = f'Prochain cours {quand} : {suivant["matiere"]}, {n} étudiants attendus.'
        if ticket['places_perdues'] > 0:
            a['raison'] += f' {restantes} places restantes : ça suffit.' if n <= restantes else f' {restantes} places restantes : pas assez.'
    else:
        a['raison'] = f'Prochain cours {quand} : {suivant["matiere"]}.'
    return a


ORDRE_URGENCE = {'urgent': 0, 'avant le prochain cours': 1, 'pas pressé': 2, None: 3}


def trier(liste):
    return sorted(liste, key=lambda x: (ORDRE_URGENCE[x['urgence']],
                                        (x['echeance'] or {}).get('date', '9'), (x['echeance'] or {}).get('heure', 99),
                                        -x['cree']))


# ---------- tickets ouverts par le jumeau ----------

def pannes_detectees(campus, t, salle_purgee):
    """Pannes que le jumeau a détectées dans les salles : {(salle, objet): [messages]}.
    La dérive du capteur n'est crue que dans la salle de l'automate (salle_purgee) : il y purge l'air
    le soir avant la mesure. Ailleurs, l'air d'un cours tardif n'est pas toujours parti à 19 h 30
    (essai : fausse dérive de 150 ppm en SAR 206)."""
    pannes = {}
    for salle in campus.salles.values():
        diagnostic = salle.etat(t)['air']['diagnostic']
        for cause, d in diagnostic.items():
            if cause == 'derive' and salle.id != salle_purgee:
                continue
            if d['etat'] == 'detecte' and cause in PANNES_JUMEAU:
                pannes.setdefault((salle.id, PANNES_JUMEAU[cause]), []).append(f'{d["titre"]} : {d["message"]}')
    return pannes
