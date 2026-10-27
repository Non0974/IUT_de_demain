"""Test des tickets : un enseignant signale des tables manquantes avant un cours ; le jumeau doit dire que
c'est urgent (plus assez de places pour ce cours), compter les places perdues dans la capacité et proposer
une autre salle. Puis : feutres signalés deux fois (un seul ticket), droits de chacun (le service technique
ne voit que les tickets), outil de l'assistant sans nom. Enfin, la ventilation de SAR 200 tombe en panne
le jeudi : le jumeau doit ouvrir un ticket tout seul, une seule fois, et aucun ailleurs.

    python tests/test_tickets.py
"""

import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import serveur     # noqa: E402
from assistant import Outils   # noqa: E402
from comptes import comptes_de_demo   # noqa: E402
from reaffectation import texte_proposition   # noqa: E402
from registre import Registre  # noqa: E402
from salle import heure_du_jour  # noqa: E402
from suivi import Refus, Suivi  # noqa: E402

PORT = 8766
ENSEIGNANT = {'login': 'enseignant', 'role': 'enseignant', 'nom': 'Enseignant (essai)', 'enseignant': 'Enseignant A'}
COLLEGUE = {'login': 'collegue', 'role': 'enseignant', 'nom': 'Collègue (essai)', 'enseignant': 'Enseignant B'}
TECHNIQUE = {'login': 'technique', 'role': 'technique', 'nom': 'Services techniques (essai)'}


class PontFactice:
    etat = {'connecte': False}

    def regler(self, *a, **k):
        pass


def appel(chemin, corps=None, cookie=None):
    req = urllib.request.Request(f'http://127.0.0.1:{PORT}{chemin}', data=json.dumps(corps).encode() if corps is not None else None,
                                 method='POST' if corps is not None else 'GET',
                                 headers={'Content-Type': 'application/json', **({'Cookie': cookie} if cookie else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read()), r.headers.get('Set-Cookie')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}'), None


def connexion(login):
    _, _, cookie = appel('/api/connexion', {'login': login, 'mot_de_passe': 'demo'})
    return cookie.split(';')[0]


def main():
    verifs = []
    campus = serveur.Campus(None, PontFactice(), Registre())
    sim = serveur.charger_simulateur('batiment').SimulateurBatiment(
        campus.recevoir, lambda s: campus.salles[s].niveau or 'petite', cours_du_jour=campus.planning.cours_du_jour)
    campus.simulation = sim
    campus.t = sim.t
    campus.ajouter_cartes(sim.annuaire())
    debut = datetime.fromtimestamp(sim.t).date()

    def jouer(jour, heure, arret=None):
        n = 0
        while (datetime.fromtimestamp(sim.t).date() - debut).days < jour or (
                (datetime.fromtimestamp(sim.t).date() - debut).days == jour and heure_du_jour(sim.t) < heure):
            sim.pas(10)
            campus.t = sim.t
            n += 1
            if n % 6 == 0:
                campus.piloter()
                campus.synchroniser(force=True)
                if arret and arret():
                    return

    jouer(0, 8.0)                                      # lundi 8 h
    jour = debut
    h = heure_du_jour(campus.t)

    # 1. Tables manquantes dans la salle d'un cours qui tenait juste : il ne tient plus
    cours = sorted(campus.planning.cours_du_jour(jour), key=lambda c: c['debut'])
    choix = None
    for c in cours:
        if not c['salle'] or c['debut'] < h + 1.5:
            continue
        places = campus.batiment_salles[c['salle']]['places']
        attendus = campus.prevision.etudiants_attendus(c, jour)
        if 0 <= places - attendus <= 6:
            choix = (c, places, attendus)
            break
    c, places, attendus = choix
    tables = (places - attendus) // 2 + 1
    r = campus.signaler(ENSEIGNANT, {'salle': c['salle'], 'objet': 'table', 'quantite': tables, 'detail': 'Tables cassées.'})
    print(f'{c["matiere"]} en {c["salle"]} à {heure_du_jour_texte(c["debut"])} : {attendus} étudiants attendus, {places} places, '
          f'{tables} tables manquantes')
    restantes = campus.places_restantes(c['salle'])
    verifs.append(('places perdues : 2 par table', restantes == places - 2 * tables))
    x = next(t for t in campus.liste_tickets() if t['id'] == r['id'])
    print(f'  ticket : {x["titre"]} | {x["urgence"]} | avant {x["echeance"]["texte"]} | {x["raison"]} | {x["creneau"]["texte"]}')
    verifs.append(('urgent : plus assez de places pour le cours', x['urgence'] == 'urgent' and 'places restantes' in x['raison']
                   and x['echeance']['heure'] <= c['debut']))
    restent = sorted((y for y in campus.planning.cours_du_jour(jour) if y['salle'] == c['salle'] and y['fin'] > h),
                     key=lambda y: y['debut'])
    libre = restent[0]['debut'] > h and campus.salles[c['salle']].nombre() == 0
    verifs.append(("quand intervenir : libre maintenant, jusqu'au prochain cours de la salle",
                   x['creneau']['maintenant'] == libre and (not libre or x['creneau']['fin'] == restent[0]['debut'])))
    cap = next(s for s in campus.previsions(frais=True)['capacite']['salles'] if s['salle'] == c['salle'])
    ligne = next(y for y in cap['cours'] if y['cours'] == c['id'])
    verifs.append(('capacité : la salle compte les places qui restent', cap['places'] == restantes
                   and cap['places_perdues'] == 2 * tables and ligne['etat'] == 'trop_petite'))
    p = next((y for y in campus.previsions()['propositions'] if y['cours'] == c['id']), None)
    print(f'  proposition : {texte_proposition(p) if p else "aucune"}')
    verifs.append(('proposition de changement de salle (matériel manquant)', p is not None and 'trop_petite' in p['motifs']
                   and p['places'] == restantes and 'matériel manquant' in texte_proposition(p)))

    # 2. Feutres : urgent si le cours est dans moins de 2 h ; signalés deux fois -> un seul ticket
    bientot = next(y for y in cours if y['salle'] and h < y['debut'] <= h + 1.5 and y['salle'] != c['salle'])
    r1 = campus.signaler(ENSEIGNANT, {'salle': bientot['salle'], 'objet': 'feutres'})
    r2 = campus.signaler(COLLEGUE, {'salle': bientot['salle'], 'objet': 'feutres', 'detail': 'Toujours rien.'})
    f = next(t for t in campus.liste_tickets() if t['id'] == r1['id'])
    verifs.append(('feutres pour un cours dans moins de 2 h : urgent', f['urgence'] == 'urgent'))
    verifs.append(('signalé deux fois : un seul ticket', r2 == {'id': r1['id'], 'deja': True} and len(f['suivi']) == 2))

    # 3. Droits : un enseignant ne change pas l'état du ticket d'un autre ; il peut fermer le sien
    try:
        campus.changer_ticket(COLLEGUE, {'id': r1['id'], 'statut': 'résolu'})
        refuse = False
    except Refus:
        refuse = True
    campus.changer_ticket(COLLEGUE, {'id': r1['id'], 'texte': 'Il en manque aussi en SAR 103.'})
    verifs.append(('enseignant : commente, mais ne ferme pas le ticket d\'un autre', refuse))

    # 4. Par le serveur web : le service technique ne voit que les tickets
    http = ThreadingHTTPServer(('127.0.0.1', PORT), serveur.creer_gestionnaire(campus, comptes_de_demo('Enseignant A')))
    http.daemon_threads = True
    threading.Thread(target=http.serve_forever, daemon=True).start()
    tech = connexion('technique')
    codes = [appel(chemin, cookie=tech)[0] for chemin in ('/api/tableau', '/api/seances', '/api/classes', '/api/etat', '/api/assistant')]
    code, d, _ = appel('/api/tickets', cookie=tech)
    verifs.append(('service technique : tickets oui, présences et salles non', codes == [403] * 5 and code == 200
                   and len(d['tickets']) == 2 and all('login' not in t for t in d['tickets'])))
    code, _, _ = appel('/api/tickets/changer', {'id': r['id'], 'statut': 'en cours'}, cookie=tech)
    ens = connexion('enseignant')
    code2, _, _ = appel('/api/tickets/changer', {'id': r['id'], 'statut': 'ouvert'}, cookie=ens)
    code3, d3, _ = appel('/api/tickets', {'salle': 'SAR 101', 'objet': 'autre', 'detail': ''}, cookie=ens)
    verifs.append(('le technicien prend en charge ; l\'enseignant ne change pas l\'état ; « Autre » demande une précision',
                   code == 200 and code2 == 403 and code3 == 400))
    http.shutdown()

    # 5. L'assistant voit les tickets, sans le nom de la personne qui a signalé
    outil = Outils(campus, Suivi(campus), {'login': 'directeur', 'role': 'directeur', 'nom': 'Directeur'}, None).tickets({})
    texte = json.dumps(outil, ensure_ascii=False)
    verifs.append(('assistant : tickets sans nom', len(outil['tickets']) == 2 and 'Enseignant (essai)' not in texte
                   and 'Collègue' not in texte))

    # 6. Résolu : les places reviennent, la proposition disparaît
    campus.changer_ticket(TECHNIQUE, {'id': r['id'], 'statut': 'résolu', 'texte': 'Tables remplacées.'})
    p = next((y for y in campus.previsions()['propositions'] if y['cours'] == c['id']), None)
    verifs.append(('résolu : places rendues, plus de salle trop petite', campus.places_restantes(c['salle']) == places
                   and (p is None or 'trop_petite' not in p['motifs'])))

    # 7. Pannes : rien pendant trois jours normaux, puis la ventilation de SAR 200 tombe en panne jeudi
    def du_jumeau():
        return [t for t in campus.liste_tickets() if t['source'] == 'jumeau']

    jouer(2, 23.9)
    avant = du_jumeau()
    sim.salles['SAR 200'].pannes['ventilation'] = True
    jouer(4, 18.0, arret=lambda: any(t['salle'] == 'SAR 200' for t in du_jumeau()))
    apres = du_jumeau()
    for t in apres:
        print(f'  ticket du jumeau : {t["salle"]} {t["titre"]} ({datetime.fromtimestamp(t["cree"]):%a %Hh%M}) : {t["detail"][:90]}')
    jouer(4, 20.0)
    verifs.append(('trois jours sans panne : aucun ticket du jumeau', not avant))
    verifs.append(('ventilation en panne : un ticket ouvert par le jumeau, une seule fois',
                   len([t for t in du_jumeau() if t['salle'] == 'SAR 200']) == 1
                   and any(t['objet'] == 'ventilation' and len(t['suivi']) == 1 for t in du_jumeau())))

    print()
    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


def heure_du_jour_texte(h):
    return f'{int(h):02d}h{round(h % 1 * 60):02d}'


if __name__ == '__main__':
    main()
