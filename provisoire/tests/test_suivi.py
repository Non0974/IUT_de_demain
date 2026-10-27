"""Test de l'interface de suivi des classes côté serveur : comptes, droits, registre, corrections, export.

Lance le serveur en simulation (avec la semaine précédente jouée d'un coup), puis l'interroge
comme le ferait le navigateur.

    python tests/test_suivi.py
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import config      # noqa: E402
import serveur     # noqa: E402
from automate import PontAutomate     # noqa: E402
from comptes import comptes_de_demo   # noqa: E402
from registre import Registre         # noqa: E402

PORT, PORT_AUTOMATE = 8765, 5041
BASE = f'http://127.0.0.1:{PORT}'


def demarrer():
    serveur.charger_simulateur('automate').demarrer(PORT_AUTOMATE)
    pont = PontAutomate('127.0.0.1', PORT_AUTOMATE, 0.5)
    campus = serveur.Campus(None, pont, Registre())
    edt = campus.edt
    enseignant = serveur.enseignant_de_demo(edt)
    comptes = comptes_de_demo(enseignant)
    pont.demarrer()
    debut = time.time()
    serveur.lancer_simulation(campus, vitesse=600, jours_historique=5)
    print(f'Semaine précédente simulée en {time.time() - debut:.0f} s')
    threading.Thread(target=campus.boucle, daemon=True).start()
    http = ThreadingHTTPServer(('127.0.0.1', PORT), serveur.creer_gestionnaire(campus, comptes))
    http.daemon_threads = True
    threading.Thread(target=http.serve_forever, daemon=True).start()
    return campus, enseignant


def appel(chemin, corps=None, cookie=None):
    req = urllib.request.Request(BASE + chemin, data=json.dumps(corps).encode() if corps is not None else None,
                                 method='POST' if corps is not None else 'GET',
                                 headers={'Content-Type': 'application/json', **({'Cookie': cookie} if cookie else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            brut = r.read()
            donnees = json.loads(brut) if r.headers.get_content_type() == 'application/json' else brut.decode('utf-8')
            return r.status, donnees, r.headers.get('Set-Cookie')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}'), None


def connexion(login, mdp):
    code, _, cookie = appel('/api/connexion', {'login': login, 'mot_de_passe': mdp})
    return code, cookie.split(';')[0] if cookie else None


def main():
    campus, enseignant = demarrer()
    verifs = []

    code, _, _ = appel('/api/tableau')
    verifs.append(('sans compte : 401', code == 401))
    code, _ = connexion('directeur', 'faux')
    verifs.append(('mauvais mot de passe : 401', code == 401))

    code, dir_ = connexion('directeur', 'demo')
    verifs.append(('connexion du directeur', code == 200 and dir_))

    code, t, _ = appel('/api/tableau', cookie=dir_)
    verifs.append(('tableau de bord', code == 200 and 'chiffres' in t))

    # Semaine précédente (jouée au démarrage) : son vendredi a des séances closes avec émargement
    lundi = (serveur.charger_simulateur('batiment').DEBUT_SEMAINE - timedelta(days=7)).date()
    vendredi, periode = lundi + timedelta(days=4), f'du={lundi}&au={lundi + timedelta(days=6)}'
    code, s, _ = appel(f'/api/seances?date={vendredi}', cookie=dir_)
    seances = s['seances']
    closes = [x for x in seances if x['etat'] == 'terminée']
    verifs.append(('séances de la semaine précédente dans le registre', code == 200 and len(closes) >= 5))
    verifs.append(('plus aucun "attendu" dans les séances closes', all(x['attendus'] == 0 for x in closes)))
    taux = sum(x['presents'] + x['retards'] for x in closes) / max(1, sum(x['inscrits'] for x in closes))
    verifs.append((f'taux de présence plausible ({taux:.0%})', 0.75 <= taux <= 0.98))

    # Détail d'une séance réelle de la classe et correction d'un absent
    seance = next(x for x in closes if x['reel'] and 'TP1' in x['cles'])
    code, d, _ = appel(f'/api/seance?id={seance["id"]}', cookie=dir_)
    absent = next((p for p in d['presences'] if p['statut'] == 'absent'), d['presences'][0])
    code, d2, _ = appel('/api/seance/statut', {'seance': seance['id'], 'etudiant': absent['etudiant'],
                                                'statut': 'justifié', 'motif': 'certificat médical'}, cookie=dir_)
    ligne = next(p for p in d2['presences'] if p['etudiant'] == absent['etudiant'])
    verifs.append(('correction enregistrée (justifié, avec motif et auteur)',
                   code == 200 and ligne['statut'] == 'justifié' and ligne['corrige'] == 1
                   and d2['corrections'][0]['motif'] == 'certificat médical' and 'Directeur' in d2['corrections'][0]['auteur']))
    code, _, _ = appel('/api/seance/statut', {'seance': seance['id'], 'etudiant': absent['etudiant'], 'statut': 'justifié'}, cookie=dir_)
    verifs.append(('absence justifiée sans motif : refusée', code == 400))

    code, c, _ = appel(f'/api/classes?{periode}', cookie=dir_)
    tp1 = next(x for x in c['classes'] if x['cle'] == 'TP1')
    verifs.append(('bilan des classes (TP1)', code == 200 and tp1['etudiants'] == 9 and tp1['taux'] is not None))
    code, cl, _ = appel(f'/api/classe?id=TP1&{periode}', cookie=dir_)
    verifs.append(('tableau de la classe TP1', code == 200 and len(cl['etudiants']) == 9 and len(cl['seances']) >= 5))
    code, e, _ = appel(f'/api/etudiant?id={absent["etudiant"]}&{periode}', cookie=dir_)
    verifs.append(('fiche étudiant avec la correction', code == 200 and e['justifies'] >= 1 and e['corrections']))
    code, csv, _ = appel(f'/api/export?classe=TP1&{periode}', cookie=dir_)
    verifs.append(('export CSV de la classe', code == 200 and 'Taux de présence' in csv and 'TP1-01' in csv))

    # Cartes : un badge inconnu apparaît, on l'attribue, le lecteur le reconnaît ensuite
    carte = '0123456789abcdef'
    code, r, _ = appel('/api/mesure', {'type': 'badge', 'salle': 'SAR 102', 'carte': carte})
    verifs.append(('lecteur : carte inconnue signalée', code == 200 and r.get('connue') is False))
    code, inc, _ = appel('/api/cartes/inconnues', cookie=dir_)
    verifs.append(('carte en attente, places de la classe proposées', code == 200 and any(c['empreinte'] == carte for c in inc['cartes'])
                   and [len(g['etudiants']) for g in inc['groupes']] == [9, 9]))
    code, _, _ = appel('/api/cartes/associer', {'empreinte': carte, 'etudiant': 'TP2-04', 'nom': 'Étudiant Test'}, cookie=dir_)
    code2, r, _ = appel('/api/mesure', {'type': 'badge', 'salle': 'SAR 102', 'carte': carte})
    code3, liste, _ = appel('/api/cartes/liste', cookie=dir_)
    tp204 = [c for c in liste['cartes'] if c['id'] == 'TP2-04']
    verifs.append(('carte enregistrée, puis reconnue par le lecteur (elle remplace l\'ancienne)', code == 200 and r.get('connue') is True
                   and len(tp204) == 1 and tp204[0]['empreinte'] == carte and tp204[0]['nom'] == 'Étudiant Test'))
    code, _, _ = appel('/api/cartes/associer', {'empreinte': carte, 'etudiant': 'TP9-99'}, cookie=dir_)
    verifs.append(('carte pour un étudiant qui n\'existe pas : refusée', code == 400))

    # Enseignant : seulement ses séances et ses classes
    code, ens = connexion('enseignant', 'demo')
    code, _, _ = appel('/api/cartes/inconnues', cookie=ens)
    verifs.append(('enseignant : page des cartes refusée', code == 403))
    code, s, _ = appel(f'/api/seances?date={vendredi}', cookie=ens)
    verifs.append(('enseignant : seulement ses séances', code == 200 and s['seances'] and all(x['enseignant'] == enseignant for x in s['seances'])))
    autre = next(x for x in seances if x['enseignant'] != enseignant)
    code, _, _ = appel(f'/api/seance?id={autre["id"]}', cookie=ens)
    verifs.append(('enseignant : séance d\'un collègue refusée', code == 403))
    code, _, _ = appel('/api/etat', cookie=ens)
    verifs.append(('enseignant : jumeau de tout le bâtiment refusé', code == 403))
    autres_classes = {k for x in seances if x['enseignant'] != enseignant for k in x['cles']}
    mes_classes = {k for c in campus.edt['cours'] if c['enseignant'] == enseignant for k in c['cles']}
    pas_a_moi = next(iter(autres_classes - mes_classes))
    code, _, _ = appel(f'/api/classe?id={pas_a_moi}', cookie=ens)
    verifs.append(('enseignant : classe d\'un collègue refusée', code == 403))

    code, _, _ = appel('/api/deconnexion', {}, cookie=dir_)
    code2, _, _ = appel('/api/tableau', cookie=dir_)
    verifs.append(('déconnexion', code == 200 and code2 == 401))

    for _ in range(6):
        code, _ = connexion('directeur', 'encore-faux')
    verifs.append(('trop d\'essais ratés : bloqué (429)', code == 429))

    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
