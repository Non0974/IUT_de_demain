"""Le RER qui prévient la salle : quand une ligne qui dessert l'IUT est perturbée, le jumeau prévoit les
retards des cours qui commencent bientôt, et explique ceux qui arrivent.

Il apprend sur les séances closes la part d'étudiants en retard selon qu'une ligne était perturbée ou non
pendant l'arrivée (de 45 min avant le cours jusqu'au début). Aucune donnée personnelle : on ne sait pas qui
prend quelle ligne, seulement combien d'étudiants arrivent en retard.

Sources :
  - en simulation, le simulateur envoie {"type": "transport", "ligne": "RER D", "perturbe": true/false} ;
  - en vrai, PontPrim lit les messages d'info trafic de l'API PRIM d'Île-de-France Mobilités (SIRI Lite
    « general-message », clé gratuite à créer sur prim.iledefrance-mobilites.fr, dans config.PRIM_CLE).
    Pas encore testé avec la vraie API : format et identifiants des lignes à vérifier avec une clé.
"""

import json
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

from registre import heure_texte

ARRIVEE = 0.75          # h avant le cours pendant lesquelles une perturbation retarde les étudiants
A_VENIR = 1.5           # h : on prévient pour les cours qui commencent dans l'heure et demie
MIN_SEANCES = 3         # séances avec perturbation avant de se fier à l'effet appris
ADRESSE_PRIM = 'https://prim.iledefrance-mobilites.fr/marketplace/general-message'


class Transports:
    def __init__(self):
        self.periodes = {}          # ligne -> [[début, fin ou None], ...]
        self.textes = {}            # ligne -> dernier message
        self.normal = [0, 0]        # [retards, étudiants arrivés] des séances sans perturbation
        self.perturbe = {}          # ligne -> [retards, arrivés, séances]
        self.appris = set()         # séances déjà comptées

    # ---------- état des lignes ----------

    def recevoir(self, t, ligne, perturbe, texte=''):
        periodes = self.periodes.setdefault(ligne, [])
        ouverte = periodes and periodes[-1][1] is None
        if perturbe and not ouverte:
            periodes.append([t, None])
        elif not perturbe and ouverte:
            periodes[-1][1] = t
        if perturbe and texte:
            self.textes[ligne] = texte

    def perturbees(self, t0, t1):
        """Lignes perturbées à un moment entre t0 et t1, avec le début et la fin de la perturbation."""
        return {ligne: (d, f) for ligne, periodes in self.periodes.items() for d, f in periodes
                if d <= t1 and (f is None or f >= t0)}

    def maintenant(self, t):
        return {ligne: d for ligne, periodes in self.periodes.items() for d, f in periodes if f is None and d <= t}

    # ---------- apprentissage ----------

    def apprendre(self, seance):
        """Une séance close : ses retards comptent pour « ligne perturbée » ou pour « normal »."""
        if seance['id'] in self.appris:
            return
        self.appris.add(seance['id'])
        arrives = seance['presents'] + seance['retards']
        if not arrives:
            return
        debut = datetime.fromisoformat(seance['date']).timestamp() + seance['debut'] * 3600
        lignes = self.perturbees(debut - ARRIVEE * 3600, debut)
        if not lignes:
            self.normal[0] += seance['retards']
            self.normal[1] += arrives
        for ligne in lignes:
            s = self.perturbe.setdefault(ligne, [0, 0, 0])
            s[0] += seance['retards']
            s[1] += arrives
            s[2] += 1

    def taux(self, ligne):
        """(part de retards d'habitude, quand la ligne est perturbée, séances perturbées vues)."""
        normal = self.normal[0] / self.normal[1] if self.normal[1] else 0.05
        s = self.perturbe.get(ligne)
        return normal, (s[0] / s[1] if s and s[1] else None), (s[2] if s else 0)

    # ---------- ce qu'on montre ----------

    def alertes(self, cours, t, attendus):
        """Cours qui commencent bientôt alors qu'une ligne est perturbée : retards attendus.
        attendus(c) : étudiants attendus au cours."""
        h = datetime.fromtimestamp(t)
        minuit = datetime(h.year, h.month, h.day).timestamp()
        alertes = []
        for ligne, depuis in self.maintenant(t).items():
            normal, perturbe, vues = self.taux(ligne)
            for c in cours:
                debut = minuit + c['debut'] * 3600
                if not t <= debut <= t + A_VENIR * 3600 or not c['salle']:
                    continue
                n = attendus(c)
                texte = f'{ligne} perturbé depuis {datetime.fromtimestamp(depuis):%Hh%M}.'
                if perturbe is not None and vues >= MIN_SEANCES:
                    texte += (f' Environ {round(n * perturbe)} retards attendus en {c["matiere"]} à {heure_texte(c["debut"])}, '
                              f'contre {round(n * normal)} d\'habitude.')
                else:
                    texte += f' Il risque d\'y avoir des retards en {c["matiere"]} à {heure_texte(c["debut"])}.'
                alertes.append({'ligne': ligne, 'cours': c['id'], 'salle': c['salle'], 'enseignant': c['enseignant'],
                                'texte': texte, 'message': self.textes.get(ligne, '')})
        return alertes

    def explication(self, seance):
        """Pour une séance : une ligne était-elle perturbée pendant l'arrivée des étudiants ?"""
        debut = datetime.fromisoformat(seance['date']).timestamp() + seance['debut'] * 3600
        lignes = self.perturbees(debut - ARRIVEE * 3600, debut)
        if not lignes:
            return None
        morceaux = [f'{l} perturbé ({datetime.fromtimestamp(d):%Hh%M} – '
                    f'{datetime.fromtimestamp(f):%Hh%M})' if f else f'{l} perturbé depuis {datetime.fromtimestamp(d):%Hh%M}'
                    for l, (d, f) in lignes.items()]
        return {'lignes': list(lignes), 'texte': f'Les retards viennent sans doute des transports ({", ".join(morceaux)}).'}


def perturbations_siri(donnees, ligne_ref):
    """Messages « Perturbation » d'une ligne dans une réponse SIRI Lite general-message."""
    textes = []
    livraisons = donnees.get('Siri', {}).get('ServiceDelivery', {}).get('GeneralMessageDelivery', [])
    for livraison in livraisons:
        for m in livraison.get('InfoMessage', []):
            canal = (m.get('InfoChannelRef') or {}).get('value', '')
            contenu = m.get('Content', {})
            lignes = [l.get('value') for l in contenu.get('LineRef', [])]
            if canal == 'Perturbation' and (not lignes or ligne_ref in lignes):
                textes.append(' '.join(x.get('MessageText', {}).get('value', '') for x in contenu.get('Message', [])).strip())
    return textes


class PontPrim:
    """Interroge l'API PRIM toutes les 2 min et transmet l'état des lignes au jumeau."""

    def __init__(self, campus, cle, lignes, periode=120):
        self.campus, self.cle, self.lignes, self.periode = campus, cle, lignes, periode
        self.erreur = None

    def demarrer(self):
        threading.Thread(target=self._boucle, daemon=True, name='prim').start()

    def _boucle(self):
        while True:
            for nom, ref in self.lignes.items():
                try:
                    url = f'{ADRESSE_PRIM}?LineRef={urllib.parse.quote(ref)}'
                    req = urllib.request.Request(url, headers={'apiKey': self.cle, 'Accept': 'application/json'})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        textes = perturbations_siri(json.loads(r.read()), ref)
                    self.campus.recevoir({'type': 'transport', 'ligne': nom, 'perturbe': bool(textes),
                                          'texte': textes[0] if textes else ''})
                    self.erreur = None
                except (OSError, ValueError) as e:        # réseau ou clé : on réessaiera
                    self.erreur = str(e)
            time.sleep(self.periode)
