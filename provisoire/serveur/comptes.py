"""Comptes de l'interface de suivi : qui peut voir et corriger les présences.

Rôles :
  directeur     directeur des études : voit tout, corrige tout, exporte
  scolarite     scolarité / vie scolaire : comme le directeur
  enseignant    voit et corrige seulement ses séances et les classes qu'il a en cours

Les mots de passe ne sont jamais gardés : seulement une empreinte PBKDF2 (sel + 200 000 tours).
Les comptes sont dans serveur/comptes.json (pas sur GitHub).

    python serveur/comptes.py ajouter directeur --role directeur --nom "Directeur des études"
    python serveur/comptes.py ajouter dupont --role enseignant --nom "M. Dupont" --enseignant "DUPONT Jean"
    python serveur/comptes.py liste
    python serveur/comptes.py supprimer dupont
"""

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

FICHIER = Path(__file__).resolve().parent / 'comptes.json'
ROLES = ('directeur', 'scolarite', 'enseignant')
TOURS = 200_000
DUREE_SESSION = 10 * 3600          # s
ESSAIS_MAX = 5                     # essais ratés par minute et par adresse avant blocage


def empreinte(mot_de_passe, sel):
    return hashlib.pbkdf2_hmac('sha256', mot_de_passe.encode(), bytes.fromhex(sel), TOURS).hex()


class Comptes:
    def __init__(self, fichier=FICHIER, comptes=None):
        self.fichier = fichier
        self.comptes = comptes if comptes is not None else (
            json.loads(fichier.read_text(encoding='utf-8')) if fichier and fichier.exists() else {})
        self.sessions = {}             # jeton -> {login, role, nom, enseignant, expire}
        self.essais = {}               # adresse -> [heures des essais ratés]
        self.verrou = threading.Lock()

    def ajouter(self, login, mot_de_passe, role, nom, enseignant=None):
        if role not in ROLES:
            raise ValueError(f'Rôle inconnu : {role}')
        if role == 'enseignant' and not enseignant:
            raise ValueError('Un compte enseignant doit être relié à son nom dans l\'emploi du temps.')
        sel = secrets.token_hex(16)
        self.comptes[login] = {'role': role, 'nom': nom, 'enseignant': enseignant, 'sel': sel,
                               'empreinte': empreinte(mot_de_passe, sel)}

    def enregistrer(self):
        self.fichier.write_text(json.dumps(self.comptes, ensure_ascii=False, indent=1), encoding='utf-8')

    def connecter(self, login, mot_de_passe, adresse):
        maintenant = time.time()
        with self.verrou:
            essais = [t for t in self.essais.get(adresse, []) if maintenant - t < 60]
            if len(essais) >= ESSAIS_MAX:
                raise PermissionError('Trop d\'essais : réessayez dans une minute.')
        compte = self.comptes.get(login)
        # On calcule l'empreinte même si le compte n'existe pas : même durée de réponse
        attendu = compte['empreinte'] if compte else '0' * 64
        calcule = empreinte(mot_de_passe, compte['sel'] if compte else '00' * 16)
        if not compte or not hmac.compare_digest(attendu, calcule):
            with self.verrou:
                self.essais[adresse] = essais + [maintenant]
            return None
        jeton = secrets.token_urlsafe(32)
        with self.verrou:
            self.essais.pop(adresse, None)
            self.sessions[jeton] = {'login': login, 'role': compte['role'], 'nom': compte['nom'],
                                    'enseignant': compte.get('enseignant'), 'expire': maintenant + DUREE_SESSION}
        return jeton

    def utilisateur(self, jeton):
        with self.verrou:
            s = self.sessions.get(jeton)
            if s and s['expire'] > time.time():
                return s
            self.sessions.pop(jeton, None)
            return None

    def deconnecter(self, jeton):
        with self.verrou:
            self.sessions.pop(jeton, None)


def comptes_de_demo(enseignant):
    """Comptes du mode simulation (en mémoire, jamais écrits sur le disque)."""
    c = Comptes(fichier=None, comptes={})
    c.ajouter('directeur', 'demo', 'directeur', 'Directeur des études (démo)')
    c.ajouter('enseignant', 'demo', 'enseignant', f'{enseignant} (démo)', enseignant)
    return c


if __name__ == '__main__':
    import argparse
    import getpass

    p = argparse.ArgumentParser(description='Comptes de l\'interface de suivi des classes')
    sous = p.add_subparsers(dest='action', required=True)
    a = sous.add_parser('ajouter')
    a.add_argument('login')
    a.add_argument('--role', choices=ROLES, required=True)
    a.add_argument('--nom', required=True, help='nom affiché')
    a.add_argument('--enseignant', help='pour un enseignant : son nom exact dans l\'emploi du temps')
    s = sous.add_parser('supprimer')
    s.add_argument('login')
    sous.add_parser('liste')
    args = p.parse_args()

    comptes = Comptes()
    if args.action == 'liste':
        for login, c in comptes.comptes.items():
            print(f'{login:15} {c["role"]:11} {c["nom"]}' + (f'  ({c["enseignant"]})' if c.get('enseignant') else ''))
    elif args.action == 'supprimer':
        comptes.comptes.pop(args.login, None)
        comptes.enregistrer()
        print('Compte supprimé.')
    else:
        mdp = getpass.getpass('Mot de passe : ')
        if len(mdp) < 10:
            raise SystemExit('Mot de passe trop court (10 caractères au moins).')
        if mdp != getpass.getpass('Encore une fois : '):
            raise SystemExit('Les deux mots de passe sont différents.')
        comptes.ajouter(args.login, mdp, args.role, args.nom, args.enseignant)
        comptes.enregistrer()
        print(f'Compte {args.login} créé.')
