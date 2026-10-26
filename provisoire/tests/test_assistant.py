"""Test de l'assistant IA, sans Internet et sans clé : un faux client joue le rôle de l'API Claude.

On vérifie surtout ce qui part vers l'IA :
  - aucun vrai nom (étudiants, enseignants), aucun identifiant d'étudiant, aucun motif d'absence ;
  - les droits : un enseignant n'a pas les outils de la direction, ni les classes des autres ;
  - le serveur remet les vrais noms dans la réponse affichée ;
  - la requête suit les règles de l'API (modèle, modèle de secours, pas d'outil imposé).

Tous les noms de ce fichier sont inventés.

    python tests/test_assistant.py
"""

import json
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import config      # noqa: E402
import serveur     # noqa: E402
from assistant import FALLBACK, SYSTEME, Assistant, ErreurIA, Indisponible, Pseudonymes   # noqa: E402
from comptes import comptes_de_demo   # noqa: E402
from registre import Registre         # noqa: E402
from salle import heure_du_jour       # noqa: E402
from suivi import Suivi               # noqa: E402

FAUX_ENSEIGNANTS = dict(zip([f'Enseignant {x}' for x in 'ABCDEFGHI'],
                            ['DUPONT Jean', 'MOREAU Claire', 'LEROY Paul', 'GARNIER Sophie', 'FAURE Marc',
                             'ROUSSEL Anne', 'BLANCHARD Luc', 'GUERIN Emma', 'MULLER Théo']))
FAUX_ETUDIANTS = {'TP1-01': 'MARTIN Léa', 'TP1-02': 'BERNARD Hugo', 'TP1-03': 'PETIT Inès',
                  'TP2-01': 'PETIT Yanis', 'TP2-02': 'ROBERT Chloé'}
MOTIF = 'certificat médical du Dr Vidal'
PORT = 8766
DIRECTEUR = {'login': 'directeur', 'role': 'directeur', 'nom': 'Directeur des études (démo)', 'enseignant': None}


class PontFactice:
    def __init__(self):
        self.etat = {'connecte': False}

    def regler(self, consigne=None, personnes=None):
        pass


def preparer():
    """Campus simulé avec de faux noms : semaine précédente jouée d'un coup, puis lundi jusqu'à 10 h 15."""
    fichier = Path(tempfile.mkdtemp()) / 'enseignants.json'
    fichier.write_text(json.dumps(FAUX_ENSEIGNANTS, ensure_ascii=False), encoding='utf-8')
    serveur.FICHIER_ENSEIGNANTS = fichier
    campus = serveur.Campus(None, PontFactice(), Registre())
    vrai = serveur.threading.Thread
    serveur.threading.Thread = lambda *a, **k: SimpleNamespace(start=lambda: None)   # pas de boucle temps réel
    try:
        serveur.lancer_simulation(campus, vitesse=600, jours_historique=5)
    finally:
        serveur.threading.Thread = vrai
    for p in campus.annuaire.values():
        if p['id'] in FAUX_ETUDIANTS:
            p['nom'] = FAUX_ETUDIANTS[p['id']]
    sim, n = campus.simulation, 0
    while heure_du_jour(sim.t) < 10.25:
        sim.pas(10)
        campus.t = sim.t
        n += 1
        if n % 6 == 0:
            campus.piloter()
            campus.synchroniser(force=True)
    return campus


# ---------- faux client de l'API ----------

def texte(t):
    return SimpleNamespace(type='text', text=t)


def outil(i, nom, **entree):
    return SimpleNamespace(type='tool_use', id=f'toolu_{i}', name=nom, input=entree)


def reponse(*blocs, stop='end_turn'):
    return SimpleNamespace(stop_reason=stop, content=list(blocs))


def en_texte(objet):
    return json.dumps(objet, default=lambda o: vars(o), ensure_ascii=False)


class FauxClient:
    """Chaque appel passe la requête au scénario du moment, qui décide de la réponse."""

    def __init__(self):
        self.requetes = []        # (paramètres, copie en texte au moment de l'appel)
        self.scenario = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._creer))

    def _creer(self, **kw):
        self.requetes.append((kw, en_texte({k: kw[k] for k in ('system', 'tools', 'messages')})))
        return self.scenario(kw)


def question_envoyee(kw):
    return next(m['content'] for m in reversed(kw['messages']) if m['role'] == 'user' and isinstance(m['content'], str))


def resultats(kw):
    """Résultats d'outils renvoyés à l'IA dans cette requête : {tool_use_id: (contenu, erreur ?)}."""
    dernier = kw['messages'][-1]['content']
    return {r['tool_use_id']: (r['content'], r.get('is_error', False)) for r in dernier if isinstance(dernier, list)}


def main():
    campus = preparer()
    suivi = Suivi(campus)
    faux = FauxClient()
    assistant = Assistant(campus, suivi, FAUX_ENSEIGNANTS, config, faux)
    jour = datetime.fromtimestamp(campus.t).date()
    verifs = []
    vu = {}

    # 1. Directeur : un nom d'étudiant et un nom d'enseignant dans la question
    def scenario_1(kw):
        if 'q1' not in vu:
            vu['q1'] = question_envoyee(kw)
            vu['jeton'] = re.search(r'ETU-\d{3}', vu['q1']).group(0)
            vu['r1'] = reponse(outil(1, 'tableau_de_bord'), outil(2, 'detail_etudiant', etudiant=vu['jeton'], du='', au=''))
            return vu['r1']
        vu['res2'] = resultats(kw)                       # copie maintenant : la liste des messages va grandir
        vu['renvoye'] = kw['messages'][-2]['content']
        return reponse(texte(f"Oui, {vu['jeton']} a badgé ce matin. Le cours d'Enseignant A se passe bien."))

    faux.scenario = scenario_1
    r = assistant.repondre(DIRECTEUR, 'session-dir', "Est-ce que Léa Martin est là ce matin ? Et le cours de M. Dupont, ça va ?")
    q = vu['q1']
    verifs.append(('question envoyée sans les vrais noms', all(m not in q for m in ('Léa', 'Martin', 'Dupont'))
                   and 'Enseignant A' in q and vu['jeton'] in q))
    verifs.append(("question précédée de l'heure du jumeau", q.startswith('[lundi ') and '10h1' in q.split(']')[0]))
    kw = faux.requetes[0][0]
    verifs.append(('modèle et modèle de secours', kw['model'] == 'claude-opus-5-5' and kw['fallbacks'] == 'default'
                   and FALLBACK in kw['betas']))
    verifs.append(("pas d'outil imposé ni de température, réflexion réglée par l'effort",
                   'tool_choice' not in kw and 'temperature' not in kw and 'thinking' not in kw
                   and kw['output_config'] == {'effort': config.ASSISTANT_EFFORT}))
    verifs.append(('10 outils stricts pour la direction', len(kw['tools']) == 10 and all(t['strict'] for t in kw['tools'])
                   and kw['system'] == SYSTEME))
    res = vu['res2']
    tableau = json.loads(res['toolu_1'][0])
    fiche = json.loads(res['toolu_2'][0])
    verifs.append(('tableau de bord lu (séances en cours)', not res['toolu_1'][1] and tableau['en_cours']))
    verifs.append(("fiche de l'étudiant sous pseudonyme", not res['toolu_2'][1] and fiche['etudiant'] == vu['jeton']
                   and fiche['seances']))
    verifs.append(('réflexion du modèle renvoyée telle quelle', vu['renvoye'] is vu['r1'].content))
    verifs.append(('vrais noms remis à l\'affichage', 'DUPONT Jean' in r['texte']
                   and r['noms'][vu['jeton']] == {'id': 'TP1-01', 'nom': 'MARTIN Léa'}))
    verifs.append(('outils consultés affichés', r['outils'] == ['Tableau de bord', 'Étudiant']))

    # 2. Même conversation : émargement d'une séance, avec un motif d'absence médical
    seance = next(s for s in campus.registre.seances_du_jour(jour) if 'TP1' in s['cles'])
    campus.registre.corriger(seance['id'], 'TP1-02', 'justifié', MOTIF, 'Mme Scolarité', campus.t)

    def scenario_2(kw):
        res = resultats(kw)
        if not res:
            return reponse(outil(3, 'seances_du_jour', date=''))
        if 'toolu_3' in res:
            vu['seances'] = json.loads(res['toolu_3'][0])
            return reponse(outil(4, 'detail_seance', seance=seance['id']))
        vu['detail'] = json.loads(res['toolu_4'][0])
        return reponse(texte('Une absence justifiée.'))

    faux.scenario = scenario_2
    assistant.repondre(DIRECTEUR, 'session-dir', f"Qui était absent au cours de {seance['matiere']} ce matin ?")
    d = vu['detail']
    verifs.append(('séances du jour lues', any(s['seance'] == seance['id'] for s in vu['seances']['seances'])))
    corrige = next(p for p in d['presences'] if p.get('corrige_a_la_main'))
    verifs.append(("motif d'absence remplacé par « motif donné : oui »", d['corrections'][0]['motif_donne'] is True
                   and 'motif' not in d['corrections'][0]))
    verifs.append(('même pseudonyme dans toute la conversation', corrige['etudiant'] == 'ETU-002'
                   and any(p['etudiant'] == vu['jeton'] for p in d['presences'])))

    # 3. Enseignant : pas les outils de la direction, pas les classes des autres
    edt = campus.edt
    nom_ens = next(c['enseignant'] for c in edt['cours'] if c['reel'] and c['salle'] == config.SALLE_AUTOMATE)
    ens = {'login': 'enseignant', 'role': 'enseignant', 'nom': f'{nom_ens} (démo)', 'enseignant': nom_ens}
    siennes = suivi.cles_de(ens)
    autre = sorted({k for c in edt['cours'] for k in c['cles']} - siennes)[0]

    def scenario_3(kw):
        res = resultats(kw)
        if not res:
            vu['outils_ens'] = [t['name'] for t in kw['tools']]
            vu['q3'] = question_envoyee(kw)
            return reponse(outil(5, 'detail_classe', classe=autre, du='', au=''), outil(6, 'previsions_air'),
                           outil(7, 'classes', du='', au=''))
        vu['res3'] = res
        return reponse(texte("Je n'ai pas accès à cette classe."))

    faux.scenario = scenario_3
    assistant.repondre(ens, 'session-ens', f'Comment va la classe {autre} ? Et les prévisions ?')
    verifs.append(("enseignant : 6 outils, pas ceux de la direction", len(vu['outils_ens']) == 6 and not
                   {'salles_maintenant', 'previsions_air', 'diagnostic_salle'} & set(vu['outils_ens'])))
    pseudo = next(p for p, v in FAUX_ENSEIGNANTS.items() if v == nom_ens)
    verifs.append(("enseignant : son pseudonyme dans le contexte, pas son nom", nom_ens not in vu['q3'] and pseudo in vu['q3']))
    res = vu['res3']
    verifs.append(("classe d'un autre enseignant refusée", res['toolu_5'][1] and res['toolu_5'][0].startswith('Refusé')))
    verifs.append(('outil de la direction refusé', res['toolu_6'][1] and res['toolu_6'][0].startswith('Refusé')))
    classes = json.loads(res['toolu_7'][0])['classes']
    verifs.append(('enseignant : seulement ses classes', classes and all(c['classe'] in siennes for c in classes)))

    # 4. Refus du modèle : rien n'est gardé de la question
    faux.scenario = lambda kw: reponse(stop='refusal')
    r = assistant.repondre(DIRECTEUR, 'session-refus', 'Question refusée')
    verifs.append(('refus du modèle', r['texte'].startswith('Je ne peux pas')
                   and assistant.conversations['session-refus'].messages == []))

    # 5. Paramètres faux, pseudonyme inconnu, salle écrite en minuscules
    def scenario_5(kw):
        res = resultats(kw)
        if not res:
            return reponse(outil(8, 'detail_etudiant', etudiant='ETU-999', du='', au=''),
                           outil(9, 'diagnostic_salle', salle=12), outil(10, 'diagnostic_salle', salle='sar  101'),
                           outil(11, 'outil_qui_n_existe_pas'), outil(13, 'capacite_salles'))
        vu['res5'] = res
        return reponse(texte('Fini.'))

    faux.scenario = scenario_5
    assistant.repondre(DIRECTEUR, 'session-dir', 'Diagnostic de la SAR 101 ?')
    res = vu['res5']
    verifs.append(('pseudonyme inconnu refusé', res['toolu_8'][1] and 'inconnu' in res['toolu_8'][0]))
    verifs.append(('paramètre qui n\'est pas un texte refusé', res['toolu_9'][1]))
    diag = json.loads(res['toolu_10'][0])
    verifs.append(('diagnostic de SAR 101 (4 causes : pas de capteurs à la porte)', not res['toolu_10'][1]
                   and diag['salle'] == 'SAR 101' and len(diag['causes']) == (5 if diag['capteurs_a_la_porte'] else 4)))
    verifs.append(('outil inconnu refusé', res['toolu_11'][1]))
    cap = json.loads(res['toolu_13'][0])
    verifs.append(('places des salles : 10 salles, créneaux libres, présence apprise', not res['toolu_13'][1]
                   and len(cap['salles']) == 10 and all('creneaux_libres' in s for s in cap['salles'])
                   and cap['presence_apprise']['groupes_du_jour']))

    # 6. Réponse coupée pendant un appel d'outil : erreur, et la conversation reste comme avant
    avant = len(assistant.conversations['session-dir'].messages)
    faux.scenario = lambda kw: reponse(outil(12, 'tableau_de_bord'), stop='max_tokens')
    try:
        assistant.repondre(DIRECTEUR, 'session-dir', 'Question trop longue')
        coupe = False
    except ErreurIA:
        coupe = len(assistant.conversations['session-dir'].messages) == avant
    verifs.append(("appel d'outil coupé : pas lancé, conversation intacte", coupe))

    # 7. Rien de personnel n'est parti vers l'IA, dans aucune requête
    envoye = '\n'.join(t for _, t in faux.requetes)
    mots = {m for n in [*FAUX_ENSEIGNANTS.values(), *FAUX_ETUDIANTS.values()] for m in n.split()}
    fuites = sorted(m for m in mots if re.search(rf'(?<![\w-]){re.escape(m)}(?![\w-])', envoye, re.IGNORECASE))
    ids = {p['id'] for p in campus.annuaire.values() if p.get('groupe') != 'enseignant'}
    fuites += sorted(i for i in ids if re.search(rf'(?<![\w-]){re.escape(i)}(?![\w-])', envoye))
    fuites += [MOTIF] if 'certificat' in envoye.lower() else []
    verifs.append((f'aucun nom, identifiant ou motif envoyé ({len(faux.requetes)} requêtes)', not fuites))
    if fuites:
        print('   fuites :', fuites[:10])

    # 8. Pseudonymes : homonymes, mots courants, accents et majuscules
    p = Pseudonymes(FAUX_ETUDIANTS, FAUX_ENSEIGNANTS)
    s = p.masquer('Est-ce que Petit était là ? Quel est le plus petit taux ? ines petit, CHLOE ROBERT, tp2-02, Claire Moreau.')
    verifs.append(('homonymes : les deux pseudonymes', s.startswith('Est-ce que (ETU-001 ou ETU-002) était là')))
    verifs.append(('un mot courant reste un mot', 'le plus petit taux' in s))
    verifs.append(('accents, majuscules et identifiants', s.count('ETU-') == 5 and 'Enseignant B' in s
                   and not re.search('ines|chloe|robert|tp2', s, re.IGNORECASE)))

    # 9. Par le serveur web, avec le faux client
    comptes = comptes_de_demo(nom_ens)
    http = ThreadingHTTPServer(('127.0.0.1', PORT), serveur.creer_gestionnaire(campus, comptes, client_ia=faux))
    http.daemon_threads = True
    threading.Thread(target=http.serve_forever, daemon=True).start()

    def appel(chemin, corps=None, cookie=None):
        req = urllib.request.Request(f'http://127.0.0.1:{PORT}{chemin}', method='POST' if corps is not None else 'GET',
                                     data=json.dumps(corps).encode() if corps is not None else None,
                                     headers={'Content-Type': 'application/json', **({'Cookie': cookie} if cookie else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as rep:
                return rep.status, json.loads(rep.read()), rep.headers.get('Set-Cookie')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}'), None

    code, _, _ = appel('/api/assistant')
    verifs.append(('sans compte : 401', code == 401))
    _, _, cookie = appel('/api/connexion', {'login': 'directeur', 'mot_de_passe': 'demo'})
    cookie = cookie.split(';')[0]
    code, etat, _ = appel('/api/assistant', cookie=cookie)
    verifs.append(('page assistant : disponible, suggestions', code == 200 and etat['disponible'] and etat['suggestions']
                   and etat['conversation'] == []))
    faux.scenario = lambda kw: reponse(texte('Tout va bien.'))
    code, r, _ = appel('/api/assistant', {'question': 'Ça va ?'}, cookie)
    code2, etat, _ = appel('/api/assistant', cookie=cookie)
    verifs.append(('question par le serveur web, puis gardée', code == 200 and r['texte'] == 'Tout va bien.'
                   and len(etat['conversation']) == 1))
    code, _, _ = appel('/api/assistant', {'question': '   '}, cookie)
    verifs.append(('question vide : 400', code == 400))
    appel('/api/assistant', {'nouvelle': True}, cookie)
    _, etat, _ = appel('/api/assistant', cookie=cookie)
    verifs.append(('nouvelle conversation', etat['conversation'] == []))
    http.shutdown()

    # 10. Sans SDK ni faux client : le serveur le dit, sans planter
    seul = Assistant(campus, suivi, {}, config)
    try:
        import anthropic  # noqa: F401
        verifs.append(('SDK installé : état lu', 'disponible' in seul.etat()))
    except ImportError:
        try:
            seul.repondre(DIRECTEUR, 'x', 'Bonjour')
            dit = False
        except Indisponible as e:
            dit = 'pip install anthropic' in str(e)
        verifs.append(('sans SDK : indisponible, avec la commande à lancer', not seul.etat()['disponible'] and dit))

    print()
    for nom, ok in verifs:
        print(f"{'OK ' if ok else 'ÉCHEC'}  {nom}")
    echecs = sum(1 for _, ok in verifs if not ok)
    print(f'\n{len(verifs) - echecs}/{len(verifs)} vérifications réussies')
    sys.exit(1 if echecs else 0)


if __name__ == '__main__':
    main()
