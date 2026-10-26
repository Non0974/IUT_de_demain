"""Assistant IA : on lui pose une question en français sur l'IUT, il répond en lisant les mêmes
données que l'interface (« Qui est en SAR 101 ? », « Qui a manqué la Physique ce matin ? »,
« Quelle salle aura l'air mauvais cet après-midi ? »).

Trois règles :
  - l'IA ne voit jamais un nom ni un numéro d'étudiant. Avant l'envoi, les étudiants deviennent
    ETU-001, ETU-002… et les enseignants « Enseignant A, B… ». Les motifs d'absence (parfois
    médicaux) ne partent pas non plus. Le serveur remet les vrais noms dans la réponse affichée ;
  - elle a les droits de la personne connectée (un enseignant : ses séances et ses classes) ;
  - elle ne fait que lire. Corriger une présence ou déplacer un cours reste un clic humain.

Modèle : Claude (API Anthropic), avec le SDK officiel  (pip install anthropic)  et la clé dans la
variable ANTHROPIC_API_KEY. Sans eux, le reste du serveur marche normalement.
"""

import json
import os
import re
import threading
import time
import traceback
import unicodedata
from collections import deque
from datetime import date, datetime, timedelta

from registre import debut_semaine, heure_texte
from salle import heure_du_jour
from suivi import TOUT_VOIR, Refus

# Si le modèle refuse une demande (filtre de sécurité qui se trompe), l'API la relance sur le modèle
# de secours conseillé par Anthropic, dans le même appel.
FALLBACK = 'server-side-fallback-2026-07-01'
MAX_TOURS = 8                   # appels d'outils enchaînés pour une question
MAX_QUESTIONS = 15              # questions par conversation, ensuite on repart de zéro (coût)
DUREE_CONVERSATION = 2 * 3600   # s sans question : la conversation est oubliée
PERIODE_MAX = 62                # jours

JOURS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre',
        'novembre', 'décembre']
COMPTES = ('presents', 'retards', 'absents', 'justifies', 'a_verifier')

SYSTEME = """Tu es l'assistant de CampusTwin, le jumeau numérique de l'IUT de Cergy-Pontoise, site de Sarcelles (bâtiment SAR). Tu aides le directeur des études, la scolarité et les enseignants à suivre les présences, l'occupation des salles et la qualité de l'air.

Comment travailler :
- Tu ne connais l'IUT qu'à travers tes outils. Appelle-les avant de répondre. Ne devine jamais un chiffre, une salle, une heure ou un statut.
- Chaque question commence par une ligne entre crochets : la date et l'heure du jumeau (c'est « maintenant »), et qui est connecté.
- Les étudiants s'appellent ETU-001, ETU-002… et les enseignants « Enseignant A », « Enseignant B »… Ce sont des pseudonymes : le serveur remet les vrais noms à l'affichage. Écris-les exactement comme les outils les donnent et n'essaie jamais de retrouver un vrai nom. « (ETU-004 ou ETU-009) » dans une question veut dire que plusieurs personnes portent ce nom : demande laquelle si ça change la réponse.
- Dans les outils, les dates sont au format AAAA-MM-JJ et les heures en heure locale (08h15).
- Émargement : présent, retard, absent, justifié, à vérifier (carte peut-être prêtée), attendu (le cours n'a pas commencé).
- Personnes dans une salle : comptage exact à la porte quand la salle est équipée, sinon estimation par le Wi-Fi (à 2 personnes près environ).
- CO₂ : bon sous 800 ppm, moyen jusqu'à 1200 ppm, mauvais au-dessus.
- Places : une salle est trop petite s'il y a plus d'étudiants que de places, pleine au-dessus de 90 %, trop grande sous 40 % (avec au moins 10 places vides).
- Si un outil répond « Refusé », la personne connectée n'a pas les droits : dis-le simplement, sans chercher à contourner.

Tu ne modifies rien. Corriger une présence se fait dans la page Séances, accepter un changement de salle dans la page Anticipation : tu peux dire où cliquer.

Ta réponse : en français, courte et directe, comme un collègue. Commence par la réponse elle-même. Phrases simples. Une liste à tirets si tu cites plusieurs éléments. Pas de tableau, pas de titre. Donne les chiffres utiles (présents, ppm, heure) sans tout recopier. Si une donnée manque, dis-le."""


def _outil(nom, direction, description, **parametres):
    """Définition d'un outil pour l'API. Tous les paramètres sont des textes, vides par défaut."""
    return {
        'nom': nom, 'direction': direction, 'parametres': tuple(parametres),
        'api': {'name': nom, 'description': description, 'strict': True, 'input_schema': {
            'type': 'object',
            'properties': {k: {'type': 'string', 'description': d} for k, d in parametres.items()},
            'required': list(parametres), 'additionalProperties': False}},
    }


PERIODE = {'du': 'Premier jour, AAAA-MM-JJ. Vide : lundi de la semaine en cours.',
           'au': 'Dernier jour, AAAA-MM-JJ. Vide : dimanche de la même semaine.'}
OUTILS = {o['nom']: o for o in [
    _outil('tableau_de_bord', False,
           "Vue d'ensemble de maintenant : séances en cours (salle, matière, groupes, enseignant, émargement, "
           "personnes comptées, CO₂), séances à venir aujourd'hui, et alertes (air, carte prêtée, absences répétées). "
           "Appelle-le en premier pour toute question sur « maintenant », « en ce moment » ou « aujourd'hui »."),
    _outil('salles_maintenant', True,
           "Chaque salle du bâtiment maintenant : personnes comptées, CO₂, cours en cours et prochain cours de la journée, "
           "alertes. Appelle-le pour « qui est dans quelle salle », « quelle salle est libre », « où est tel groupe »."),
    _outil('seances_du_jour', False,
           "Séances d'un jour (terminées, en cours, à venir) avec leurs chiffres d'émargement. Appelle-le pour une "
           "question sur un jour précis, pour l'emploi du temps d'un enseignant ou d'un groupe, ou pour trouver "
           "l'identifiant d'une séance.",
           date='Jour voulu, AAAA-MM-JJ. Vide : aujourd\'hui.'),
    _outil('detail_seance', False,
           "Émargement complet d'une séance : statut de chaque étudiant (ETU-…), heure de badge, anomalies (carte "
           "prêtée, entrée sans badge), corrections faites à la main. Appelle-le pour savoir qui était absent ou en "
           "retard à un cours.",
           seance='Identifiant de la séance donné par seances_du_jour ou tableau_de_bord (ex. 2026-03-16_r3).'),
    _outil('classes', False,
           "Taux de présence de chaque classe (groupe) sur une période. Appelle-le pour comparer les classes ou "
           "pour trouver la clé d'une classe.", **PERIODE),
    _outil('detail_classe', False,
           "Une classe sur une période : chaque étudiant (ETU-…) avec ses présences, retards et absences, et les "
           "séances manquées. Appelle-le pour savoir qui décroche dans une classe.",
           classe='Clé de la classe donnée par l\'outil classes (ex. TP1).', **PERIODE),
    _outil('detail_etudiant', False,
           "Un étudiant sur une période : chaque séance avec son statut et son heure de badge, et les corrections. "
           "Appelle-le pour toute question sur un étudiant précis.",
           etudiant='Pseudonyme de l\'étudiant (ETU-…), donné par un autre outil ou par la question.', **PERIODE),
    _outil('previsions_air', True,
           "Ce que le jumeau prévoit pour les 2 prochaines heures : pic de CO₂ de chaque salle et son heure, heure "
           "de dépassement de 1000 et 1200 ppm, plan de ventilation de la salle de l'automate et énergie économisée, "
           "propositions de changement de salle (air mauvais ou salle trop petite). Appelle-le pour toute question sur "
           "l'avenir, l'air, l'énergie ou un déplacement de cours."),
    _outil('capacite_salles', True,
           "Places des salles aujourd'hui : pour chaque salle, ses places et ses cours (étudiants comptés pour un cours "
           "commencé, prévus pour un cours à venir avec le taux de présence appris pour chaque groupe), salles trop "
           "petites, pleines ou trop grandes, et créneaux libres. Appelle-le pour toute question de place : salle trop "
           "petite ou trop grande, salle libre de N places à une heure donnée, taux d'occupation des salles."),
    _outil('diagnostic_salle', True,
           "Diagnostic d'une salle : CO₂ mesuré et corrigé, débit d'air mesuré et attendu, recalage, et les causes "
           "surveillées (ventilation en panne, fenêtre ouverte, capteur qui dérive, capteur mal placé, et comptage "
           "faux si la salle a des capteurs à la porte). Appelle-le pour comprendre pourquoi une salle a un problème.",
           salle='Nom de la salle (ex. SAR 101).'),
]}
# Toujours la même liste dans le même ordre : le début de la requête ne change pas, l'API le garde en cache
DEFINITIONS = {
    'direction': [o['api'] for o in OUTILS.values()],
    'enseignant': [o['api'] for o in OUTILS.values() if not o['direction']],
}
LIBELLES = {'tableau_de_bord': 'Tableau de bord', 'salles_maintenant': 'Salles', 'seances_du_jour': 'Séances du jour',
            'detail_seance': 'Émargement', 'classes': 'Classes', 'detail_classe': 'Classe', 'detail_etudiant': 'Étudiant',
            'previsions_air': 'Prévisions', 'diagnostic_salle': 'Diagnostic', 'capacite_salles': 'Places des salles'}
SUGGESTIONS = {
    'direction': ['Qui est dans quelle salle en ce moment ?', 'Qui est absent dans les cours de ce matin ?',
                  "Quelle salle aura l'air mauvais dans les deux heures ?", 'Quelle classe a le plus d\'absences cette semaine ?',
                  'Pourquoi le CO₂ monte en SAR 101 ?', "Combien d'énergie la ventilation a économisé aujourd'hui ?",
                  'Trouve une salle libre de 25 places cet après-midi.'],
    'enseignant': ['Qui est absent à mon cours en ce moment ?', "Où et quand j'ai cours demain ?",
                   'Quels étudiants de mes classes ont le plus d\'absences cette semaine ?'],
}


class Indisponible(Exception):
    """L'assistant ne peut pas répondre (SDK absent, pas de clé…)."""


class Occupe(Exception):
    """Une question est déjà en cours, ou trop de questions cette heure-ci."""


class ErreurIA(Exception):
    """L'appel à l'API a échoué."""


# ---------- pseudonymes ----------

def _normaliser(texte):
    """Minuscules sans accents, et la position de chaque caractère dans le texte d'origine."""
    sortie, positions = [], []
    for i, ch in enumerate(texte):
        for c in unicodedata.normalize('NFD', ch.casefold()):
            if not unicodedata.combining(c):
                sortie.append(c)
                positions.append(i)
    return ''.join(sortie), positions


def _variantes(nom):
    """Façons d'écrire un nom : « DUPONT Jean », « Jean DUPONT », et « Dupont » seul
    quand le nom de famille est en majuscules."""
    mots = nom.split()
    v = {' '.join(mots)}
    famille = [m for m in mots if m.isupper() and len(m) > 1]
    prenoms = [m for m in mots if m not in famille]
    if famille and prenoms:
        v |= {' '.join(prenoms + famille), ' '.join(famille)}
    elif len(mots) == 2:
        v.add(f'{mots[1]} {mots[0]}')
    return {_normaliser(x)[0] for x in v}


class Pseudonymes:
    """Ce que voit l'IA à la place des personnes. Un jeu par conversation : ETU-001 n'a de sens
    que dans la conversation où il a été donné."""

    def __init__(self, etudiants, enseignants):
        """etudiants : identifiant -> vrai nom (ou None) ; enseignants : « Enseignant A » -> vrai nom."""
        self.etudiants = etudiants
        self.vrai_nom = dict(enseignants)
        self.pseudo = {vrai: p for p, vrai in enseignants.items()}
        self.jetons = {}                     # identifiant -> ETU-001
        self.ids = {}                        # ETU-001 -> identifiant
        cibles = {}
        for ident, nom in etudiants.items():
            for v in {_normaliser(ident)[0]} | (_variantes(nom) if nom else set()):
                cibles.setdefault(v, set()).add(('etudiant', ident))
        for vrai, pseudo in self.pseudo.items():
            for v in _variantes(vrai):
                cibles.setdefault(v, set()).add(('enseignant', pseudo))
        self.cibles = {v: sorted(p) for v, p in cibles.items() if len(v) >= 3}
        motifs = sorted(self.cibles, key=len, reverse=True)
        self.motif = re.compile(r'(?<![\w-])(?:' + '|'.join(r'\s+'.join(map(re.escape, m.split())) for m in motifs)
                                + r')(?![\w-])') if motifs else None

    def jeton(self, ident):
        if ident not in self.jetons:
            j = f'ETU-{len(self.jetons) + 1:03d}'
            self.jetons[ident] = j
            self.ids[j] = ident
        return self.jetons[ident]

    def enseignant(self, nom):
        return self.pseudo.get(nom, nom)

    def etudiant(self, jeton):
        """ETU-001 -> identifiant de l'étudiant."""
        ident = self.ids.get(jeton.strip().upper())
        if ident is None:
            raise KeyError(f'Étudiant inconnu : {jeton}. Il faut un pseudonyme ETU-… donné par un outil ou par la question.')
        return ident

    def masquer(self, texte):
        """Remplace dans un texte les noms et identifiants connus par leurs pseudonymes."""
        if not self.motif or not texte:
            return texte
        norm, pos = _normaliser(texte)
        trouves = []
        for m in self.motif.finditer(norm):
            cle = re.sub(r'\s+', ' ', m.group(0))
            debut, fin = pos[m.start()], pos[m.end() - 1] + 1
            # Un nom de famille seul ne compte que s'il commence par une majuscule : « petit » reste un mot
            if ' ' not in cle and not any(c.isdigit() for c in cle) and not texte[debut].isupper():
                continue
            noms = [self.jeton(v) if genre == 'etudiant' else v for genre, v in self.cibles[cle]]
            trouves.append((debut, fin, noms[0] if len(noms) == 1 else f'({" ou ".join(noms)})'))
        for debut, fin, remplacement in reversed(trouves):
            texte = texte[:debut] + remplacement + texte[fin:]
        return texte

    def afficher(self, texte):
        """Réponse de l'IA -> texte affiché : vrais noms des enseignants, et les étudiants cités."""
        noms = {}
        for j in sorted(set(re.findall(r'ETU-\d{3,}', texte))):
            if j in self.ids:
                ident = self.ids[j]
                noms[j] = {'id': ident, 'nom': self.etudiants.get(ident) or ident}
        texte = re.sub(r'\bEnseignant [A-Z]\b', lambda m: self.vrai_nom.get(m.group(0), m.group(0)), texte)
        return texte, noms


# ---------- outils ----------

def _jour(texte, defaut):
    texte = (texte or '').strip()
    if not texte:
        return defaut
    try:
        return date.fromisoformat(texte)
    except ValueError:
        raise ValueError(f'Date incorrecte : {texte} (format AAAA-MM-JJ).') from None


def _heure(h):
    return heure_texte(h) if h is not None else None


def _badge(t):
    return datetime.fromtimestamp(t).strftime('%Hh%M') if t else None


def _arrondi(x):
    return round(x, 2) if x is not None else None


class Outils:
    """Ce que l'IA peut lire : les pages de l'interface, avec les droits de la personne connectée.
    Seuls les champs utiles partent (pas de nom, pas de motif d'absence, pas d'auteur de correction)."""

    def __init__(self, campus, suivi, utilisateur, pseudo):
        self.campus, self.suivi, self.u, self.p = campus, suivi, utilisateur, pseudo

    def executer(self, nom, entree):
        """Lance l'outil demandé par l'IA. Renvoie (texte envoyé à l'IA, erreur ?)."""
        definition = OUTILS.get(nom)
        try:
            if definition is None or (definition['direction'] and self.u['role'] not in TOUT_VOIR):
                raise Refus(f'outil {nom} non autorisé pour cette personne.')
            if not isinstance(entree, dict) or any(not isinstance(entree.get(k, ''), str) for k in definition['parametres']):
                raise ValueError('paramètres incorrects : il faut des textes.')
            resultat = getattr(self, nom)(entree)       # nom vérifié dans OUTILS juste au-dessus
            return json.dumps(self._masquer(resultat), ensure_ascii=False), False
        except Refus as e:
            return self.p.masquer(f'Refusé : {e}'), True
        except (KeyError, ValueError) as e:
            return self.p.masquer(f'Erreur : {str(e).strip(chr(34) + chr(39))}'), True
        except Exception:                                 # un outil qui plante ne doit pas arrêter la conversation
            traceback.print_exc()
            return 'Erreur interne de cet outil.', True

    def _masquer(self, x):
        """Dernière passe sur tout le texte envoyé : un nom ou un identifiant oublié est remplacé."""
        if isinstance(x, str):
            return self.p.masquer(x)
        if isinstance(x, dict):
            return {k: self._masquer(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [self._masquer(v) for v in x]
        return x

    def _maintenant(self):
        with self.campus.verrou:
            return self.campus.t

    def _periode(self, e):
        lundi = debut_semaine(datetime.fromtimestamp(self._maintenant()).date())
        du = _jour(e.get('du'), lundi)
        au = _jour(e.get('au'), du + timedelta(days=6))
        if au < du:
            du, au = au, du
        if (au - du).days > PERIODE_MAX:
            raise ValueError('période trop longue : deux mois au plus.')
        return du, au

    def _seance(self, s):
        return {
            'seance': s['id'], 'date': s['date'], 'salle': s['salle'],
            'debut': heure_texte(s['debut']), 'fin': heure_texte(s['fin']), 'matiere': s['matiere'],
            'enseignant': self.p.enseignant(s['enseignant']), 'groupes': s['groupes'], 'etat': s.get('etat'),
            'emargement': {k: s.get(k) or 0 for k in ('inscrits', *COMPTES, 'attendus')},
        }

    def _cours(self, c):
        return {'matiere': c['matiere'], 'groupes': c['groupes'], 'enseignant': self.p.enseignant(c['enseignant']),
                'debut': heure_texte(c['debut']), 'fin': heure_texte(c['fin'])}

    # ---------- pour tous ----------

    def tableau_de_bord(self, e):
        d = self.suivi.tableau(self.u)
        chiffres = dict(d['chiffres'], taux_jour=_arrondi(d['chiffres']['taux_jour']))
        niveaux = {'detecte': 'problème', 'suspect': 'à vérifier'}
        return {
            'chiffres': chiffres,
            'en_cours': [self._seance(s) | {'personnes_comptees': s['personnes'], 'comptage': s['source'],
                                            'co2_ppm': s['co2'], 'alertes': [a['texte'] for a in s['alertes']]}
                         for s in d['en_cours']],
            'a_venir_aujourd_hui': [self._cours(c) | {'salle': c['salle'], 'effectif': c['effectif']} for c in d['a_venir']],
            'alertes': [{'niveau': niveaux.get(a['niveau'], a['niveau']), 'texte': a['texte'],
                         **({'salle': a['salle']} if a.get('salle') else {}),
                         **({'etudiant': self.p.jeton(a['etudiant'])} if a.get('etudiant') else {})}
                        for a in d['alertes']],
        }

    def seances_du_jour(self, e):
        jour = _jour(e.get('date'), datetime.fromtimestamp(self._maintenant()).date())
        d = self.suivi.seances(self.u, jour)
        return {'date': d['date'], 'jour': JOURS[jour.weekday()], 'seances': [self._seance(s) for s in d['seances']]}

    def detail_seance(self, e):
        s = self.suivi.seance(self.u, (e.get('seance') or '').strip())
        r = self._seance(s) | {
            'presences': [{'etudiant': self.p.jeton(x['etudiant']), 'statut': x['statut'], 'badge': _badge(x['badge']),
                           **({'corrige_a_la_main': True} if x['corrige'] else {})} for x in s['presences']],
            'anomalies': [{'type': a['type'], 'nombre': a['nombre'], 'detail': a['detail']} for a in s['anomalies']],
            'corrections': [{'etudiant': self.p.jeton(c['etudiant']), 'avant': c['avant'], 'apres': c['apres'],
                             'motif_donne': bool(c['motif'])} for c in s['corrections']],
        }
        if 'salle_maintenant' in s:
            m = s['salle_maintenant']
            r['salle_maintenant'] = {'personnes': m['personnes'], 'comptage': m['source'], 'co2_ppm': m['co2'],
                                     'alertes': [a['texte'] for a in m['alertes']]}
        return r

    def classes(self, e):
        d = self.suivi.classes(self.u, *self._periode(e))
        return {'du': d['du'], 'au': d['au'], 'classes': [
            {'classe': c['cle'], 'nom': c['nom'], 'etudiants': c['etudiants'], 'seances': c['seances'],
             'taux_presence': _arrondi(c['taux']), **{k: c[k] or 0 for k in COMPTES}} for c in d['classes']]}

    def detail_classe(self, e):
        du, au = self._periode(e)
        cle = (e.get('classe') or '').strip()
        noms = self.campus.registre.noms_groupes
        if cle not in noms:                      # l'IA a peut-être donné le nom (« GEIIS BUT ESE FA S5 TP1 ») au lieu de la clé
            cle = next((k for k, n in noms.items() if n.casefold() == cle.casefold()), cle)
        d = self.suivi.classe(self.u, cle, du, au)

        def seances_ou(cases, statut):
            return [s for s, c in cases.items() if c['statut'] == statut]

        return {
            'classe': d['cle'], 'nom': d['nom'], 'du': d['du'], 'au': d['au'],
            'seances': [{'seance': s['id'], 'date': s['date'], 'debut': heure_texte(s['debut']), 'matiere': s['matiere'],
                         'salle': s['salle']} for s in d['seances']],
            'etudiants': [{'etudiant': self.p.jeton(x['id']), 'taux_presence': _arrondi(x['taux']),
                           **{k: x[k] for k in COMPTES}, 'absent_a': seances_ou(x['cases'], 'absent'),
                           'en_retard_a': seances_ou(x['cases'], 'retard')} for x in d['etudiants']],
        }

    def detail_etudiant(self, e):
        du, au = self._periode(e)
        ident = self.p.etudiant(e.get('etudiant') or '')
        d = self.suivi.etudiant(self.u, ident, du, au)
        return {
            'etudiant': self.p.jeton(ident), 'classe': d['nom_groupe'], 'du': d['du'], 'au': d['au'],
            'taux_presence': _arrondi(d['taux']), **{k: d[k] for k in COMPTES},
            'seances': [{'seance': s['seance'], 'date': s['date'], 'debut': heure_texte(s['debut']),
                         'fin': heure_texte(s['fin']), 'matiere': s['matiere'], 'salle': s['salle'],
                         'enseignant': self.p.enseignant(s['enseignant']), 'statut': s['statut'], 'badge': _badge(s['badge'])}
                        for s in d['seances']],
            'corrections': [{'seance': c['seance'], 'avant': c['avant'], 'apres': c['apres'], 'motif_donne': bool(c['motif'])}
                            for c in d['corrections']],
        }

    # ---------- direction et scolarité ----------

    def salles_maintenant(self, e):
        campus = self.campus
        with campus.verrou:
            t = campus.t
            h = heure_du_jour(t)
            planning = campus.planning.cours_du_jour(datetime.fromtimestamp(t).date())
            salles = []
            for info in campus.batiment['salles']:
                etat = campus.salles[info['id']].etat(t)
                prochain = min((c for c in planning if c['salle'] == info['id'] and c['debut'] > h),
                               key=lambda c: c['debut'], default=None)
                salles.append({
                    'salle': info['id'], 'type': info['libelle'], 'etage': info['etage'], 'places': info['places'],
                    'personnes': etat['personnes'],
                    'comptage': 'porte (exact)' if etat['source'] == 'porte' else 'Wi-Fi (estimation)',
                    'co2_ppm': etat['co2'],
                    'cours_en_cours': [self._cours(c) | {'seance': c['seance'], 'badges': c['badges']} for c in etat['cours']],
                    'prochain_cours': self._cours(prochain) if prochain else None,
                    'alertes': [a['texte'] for a in etat['alertes']],
                })
        return {'heure': heure_texte(h), 'salles': salles}

    def previsions_air(self, e):
        p = self.campus.previsions()
        cmd = p['commande']
        bilan = {k: v for k, v in (cmd['bilan'] or {}).items() if k != 'c_regle'}
        debits = {'automate': 'connu (automate)', 'appris': 'appris par le jumeau', 'a priori': 'pas encore mesuré'}
        return {
            'heure': _heure(p['heure']),
            'salles': [{'salle': s['salle'], 'co2_maintenant': s['maintenant'],
                        'pic_ppm': s['pic']['co2'] if s['pic'] else None, 'pic_vers': _heure(s['pic']['heure']) if s['pic'] else None,
                        'depasse_1000_a': _heure(s['au_dessus_1000']), 'depasse_1200_a': _heure(s['au_dessus_1200']),
                        'debit_air': debits.get(s['source_debit'], s['source_debit'])} for s in p['salles']],
            'ventilation_automate': {
                'salle': cmd['salle'], 'mode': 'automatique' if cmd['auto'] else 'manuel',
                'strategie': 'jumeau prédictif' if cmd['strategie'] == 'predictive' else 'règle simple',
                'vitesse_actuelle': cmd['niveau'],
                'plan': [{'de': _heure(x['debut']), 'a': _heure(x['fin']), 'vitesse': x['niveau']} for x in cmd['plan']],
                'bilan_du_jour': bilan},
            'propositions_de_salle': [
                {'cours': x['cours'], 'matiere': x['matiere'], 'groupes': x['groupes'],
                 'enseignant': self.p.enseignant(x['enseignant']), 'de': _heure(x['debut']), 'a': _heure(x['fin']),
                 'raisons': [{'air': 'air mauvais prévu', 'trop_petite': 'salle trop petite'}[m] for m in x['motifs']],
                 'etudiants_attendus': x['etudiants'], 'salle_prevue': x['salle'], 'places': x['places'],
                 'pic_prevu_ppm': x['pic'], 'salle_proposee': x['proposee'] or 'aucune salle libre assez grande',
                 'places_salle_proposee': x['places_proposee'], 'pic_avec_changement_ppm': x['pic_propose']}
                for x in p['propositions']],
            'changements_acceptes_aujourd_hui': [{'cours': c['cours'], 'de': c['salle_avant'], 'vers': c['salle_apres']}
                                                 for c in p['changements']],
            'erreur_moyenne_des_previsions_ppm': p['precision'],
        }

    def capacite_salles(self, e):
        cap = self.campus.previsions()['capacite']
        etats = {'trop_petite': 'trop petite', 'pleine': 'pleine', 'adaptee': 'adaptée', 'trop_grande': 'trop grande'}
        sources = {'porte': 'comptés à la porte', 'badges': 'badgés', 'prévu': 'prévus'}
        ouverture, fermeture = cap['journee'][0], 19.0

        def libres(cours):
            creneaux, h = [], ouverture
            for c in cours:
                if c['debut'] - h >= 0.5:
                    creneaux.append(f'{heure_texte(h)}-{heure_texte(c["debut"])}')
                h = max(h, c['fin'])
            if fermeture - h >= 0.5:
                creneaux.append(f'{heure_texte(h)}-{heure_texte(fermeture)}')
            return creneaux

        ch = cap['chiffres']
        a = cap['appris']
        return {
            'heure': _heure(cap['heure']),
            'chiffres': {'remplissage_moyen': ch['remplissage_moyen'], 'occupation_des_salles_8h_18h': ch['occupation'],
                         'cours_salle_trop_petite': ch['trop_petite'], 'cours_salle_pleine': ch['pleine'],
                         'cours_salle_trop_grande': ch['trop_grande']},
            'salles': [{
                'salle': s['salle'], 'type': s['libelle'], 'places': s['places'], 'occupation_8h_18h': s['occupation'],
                'creneaux_libres': libres(s['cours']),
                'cours': [{'cours': c['cours'], 'matiere': c['matiere'], 'groupes': c['groupes'],
                           'enseignant': self.p.enseignant(c['enseignant']), 'de': _heure(c['debut']), 'a': _heure(c['fin']),
                           'moment': c['moment'], 'inscrits': c['inscrits'], 'etudiants': c['etudiants'],
                           'etudiants_sont': sources[c['source']], 'remplissage': c['remplissage'], 'salle_est': etats[c['etat']],
                           **({'salle_plus_petite_libre': c['plus_petite']['salle']} if c['plus_petite'] else {})}
                          for c in s['cours']],
            } for s in cap['salles']],
            'presence_apprise': {'taux_moyen': a['moyen'], 'effet_demi_journee_aujourd_hui': a['demi_journees'],
                                 'groupes_du_jour': [{'classe': g['cle'], 'nom': g['nom'], 'taux': g['taux']} for g in a['groupes']]},
        }

    def diagnostic_salle(self, e):
        sid = ' '.join((e.get('salle') or '').upper().split())
        salle = self.campus.salles.get(sid)
        if salle is None:
            raise KeyError(f'salle inconnue : {e.get("salle")}. Salles : {", ".join(self.campus.salles)}.')
        with self.campus.verrou:
            etat = salle.etat(self.campus.t)
        air = etat['air']
        etats = {'ok': 'ok', 'attente': 'en attente', 'suspect': 'à vérifier', 'detecte': 'détecté'}
        return {
            'salle': sid, 'capteurs_a_la_porte': bool(salle.porte), 'personnes': etat['personnes'],
            'co2_ppm': etat['co2'], 'co2_brut_du_capteur': round(etat['co2_brut']) if etat['co2_brut'] is not None else None,
            'correction_ppm': air['correction'], 'temperature': etat['temp'], 'ventilation': etat['niveau'],
            'debit_air_m3h': {'pendant_le_cours': air['q_occupation'], 'apres_le_depart': air['q_decroissance'],
                              'attendu': air['q_attendu']},
            'recalage': air['calibration'] or 'terminé', 'biais_du_comptage': air['biais'],
            'causes': [{'cause': c['titre'], 'etat': etats.get(c['etat'], c['etat']), 'detail': c['message']}
                       for c in air['diagnostic'].values()],
            'wifi': {'appareils': etat['appareils'], 'personnes_estimees': etat['n_wifi']},
        }


# ---------- conversations ----------

class Conversation:
    def __init__(self, utilisateur, pseudo):
        self.role = utilisateur['role']
        self.pseudo = pseudo
        self.messages = []       # envoyés à l'API tels quels, avec les blocs de réflexion du modèle
        self.affichage = []      # ce que montre la page
        self.verrou = threading.Lock()
        self.derniere = time.time()


class Assistant:
    def __init__(self, campus, suivi, enseignants, config, client=None):
        """enseignants : « Enseignant A » -> vrai nom ; client : pour les tests (faux client)."""
        self.campus, self.suivi, self.enseignants, self.config = campus, suivi, enseignants, config
        self.client = client
        self.sdk = None
        self.conversations = {}  # jeton de session -> Conversation
        self.questions = {}      # login -> heures des dernières questions
        self.verrou = threading.Lock()

    # ---------- état ----------

    def etat(self):
        """Pour la page : l'assistant peut-il répondre ?"""
        if self.client is not None:
            return {'disponible': True, 'raison': None, 'modele': self.config.ASSISTANT_MODELE}
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return {'disponible': False, 'modele': self.config.ASSISTANT_MODELE,
                    'raison': "Le SDK Anthropic n'est pas installé sur le serveur : pip install anthropic"}
        cle = os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN')
        return {'disponible': True, 'modele': self.config.ASSISTANT_MODELE,
                'raison': None if cle else "Pas de variable ANTHROPIC_API_KEY sur le serveur : l'appel risque d'échouer."}

    def _client(self):
        if self.client is None:
            try:
                import anthropic
            except ImportError:
                raise Indisponible("Le SDK Anthropic n'est pas installé sur le serveur : pip install anthropic") from None
            self.sdk = anthropic
            self.client = anthropic.Anthropic(timeout=120.0, max_retries=2)
        return self.client

    # ---------- questions ----------

    def historique(self, jeton):
        conv = self.conversations.get(jeton)
        return conv.affichage if conv else []

    def oublier(self, jeton):
        with self.verrou:
            self.conversations.pop(jeton, None)

    def _conversation(self, utilisateur, jeton):
        with self.verrou:
            maintenant = time.time()
            for j in [j for j, c in self.conversations.items() if maintenant - c.derniere > DUREE_CONVERSATION]:
                del self.conversations[j]
            conv = self.conversations.get(jeton)
            if conv is None or conv.role != utilisateur['role'] or len(conv.affichage) >= MAX_QUESTIONS:
                etudiants = {p['id']: p.get('nom') for p in self.campus.annuaire.values() if p.get('groupe') != 'enseignant'}
                conv = self.conversations[jeton] = Conversation(utilisateur, Pseudonymes(etudiants, self.enseignants))
            conv.derniere = maintenant
            return conv

    def _limiter(self, login):
        with self.verrou:
            q = self.questions.setdefault(login, deque())
            maintenant = time.time()
            while q and maintenant - q[0] > 3600:
                q.popleft()
            if len(q) >= self.config.ASSISTANT_QUESTIONS_PAR_HEURE:
                raise Occupe('Trop de questions cette heure-ci. Réessayez un peu plus tard.')
            q.append(maintenant)

    def _contexte(self, utilisateur, pseudo):
        d = datetime.fromtimestamp(self.campus.t)
        if utilisateur['role'] == 'enseignant':
            qui = f'{pseudo.enseignant(utilisateur["enseignant"])}, enseignant (voit seulement ses séances et ses classes)'
        else:
            qui = {'directeur': 'le directeur des études', 'scolarite': 'la scolarité'}.get(utilisateur['role'], utilisateur['role'])
        simulation = ' Données simulées pour la démonstration.' if self.campus.simulation else ''
        return f'[{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}, {d:%H}h{d:%M}. Connecté : {qui}.{simulation}]'

    def repondre(self, utilisateur, jeton, question):
        question = (question or '').strip()
        if not question:
            raise ValueError('Question vide.')
        if len(question) > 1000:
            raise ValueError('Question trop longue (1000 caractères au plus).')
        client = self._client()
        conv = self._conversation(utilisateur, jeton)
        if not conv.verrou.acquire(blocking=False):
            raise Occupe("Une question est déjà en cours : attendez sa réponse.")
        try:
            self._limiter(utilisateur['login'])
            return self._repondre(client, conv, utilisateur, question)
        finally:
            conv.verrou.release()

    def _repondre(self, client, conv, utilisateur, question):
        debut = time.time()
        p = conv.pseudo
        envoye = p.masquer(question)
        avant = len(conv.messages)
        conv.messages.append({'role': 'user', 'content': f'{self._contexte(utilisateur, p)}\n{envoye}'})
        outils = Outils(self.campus, self.suivi, utilisateur, p)
        consultes = []
        try:
            texte = self._boucle(client, conv, outils, consultes)
        except Exception as e:
            del conv.messages[avant:]               # la conversation repart d'avant la question
            print(f"Assistant : pas de réponse ({type(e).__name__} : {e})")
            raise ErreurIA(self._message_erreur(e)) from e
        if texte is None:                           # refus du modèle (et du modèle de secours)
            del conv.messages[avant:]
            texte = 'Je ne peux pas répondre à cette question.'
        affiche, noms = p.afficher(texte)
        entree = {'question': question, 'envoye': envoye, 'texte': affiche, 'noms': noms,
                  'outils': list(dict.fromkeys(consultes)), 'duree': round(time.time() - debut, 1)}
        conv.affichage.append(entree)
        return entree

    def _boucle(self, client, conv, outils, consultes):
        definitions = DEFINITIONS['direction' if conv.role in TOUT_VOIR else 'enseignant']
        for _ in range(MAX_TOURS):
            r = client.beta.messages.create(
                model=self.config.ASSISTANT_MODELE,
                max_tokens=16000,
                betas=[FALLBACK],
                fallbacks='default',
                output_config={'effort': self.config.ASSISTANT_EFFORT},
                cache_control={'type': 'ephemeral'},
                system=SYSTEME,
                tools=definitions,
                messages=conv.messages,
            )
            if r.stop_reason == 'refusal':
                return None
            conv.messages.append({'role': 'assistant', 'content': r.content})
            appels = [b for b in r.content if b.type == 'tool_use']
            if not appels:
                texte = '\n\n'.join(b.text for b in r.content if b.type == 'text').strip()
                if r.stop_reason == 'max_tokens':
                    texte += '\n\n(Réponse coupée : trop longue.)'
                return texte or "Je n'ai pas trouvé de réponse."
            if r.stop_reason == 'max_tokens':        # un appel d'outil coupé au milieu : on ne le lance pas
                raise RuntimeError("réponse coupée pendant un appel d'outil")
            resultats = []
            for b in appels:
                contenu, erreur = outils.executer(b.name, b.input)
                consultes.append(LIBELLES.get(b.name, b.name))
                resultats.append({'type': 'tool_result', 'tool_use_id': b.id, 'content': contenu,
                                  **({'is_error': True} if erreur else {})})
            conv.messages.append({'role': 'user', 'content': resultats})
        return "J'ai consulté beaucoup de données sans arriver à une réponse. Posez une question plus précise."

    def _message_erreur(self, e):
        a = self.sdk
        if a is not None:
            if isinstance(e, a.AuthenticationError):
                return 'Clé API refusée : vérifier ANTHROPIC_API_KEY sur le serveur.'
            if isinstance(e, a.RateLimitError):
                return "Trop de demandes à l'API Claude en même temps. Réessayez dans une minute."
            if isinstance(e, a.APIConnectionError):
                return "Pas de connexion à l'API Claude (Internet coupé ?)."
            if isinstance(e, a.APIStatusError):
                return f"L'API Claude a répondu une erreur ({e.status_code})."
        if 'authentication' in str(e).lower() or 'api_key' in str(e).lower():
            return 'Pas de clé API : mettre la clé dans la variable ANTHROPIC_API_KEY, puis relancer le serveur.'
        return f"L'assistant n'a pas pu répondre ({type(e).__name__})."
