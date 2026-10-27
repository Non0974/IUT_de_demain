"""Test du serveur sur le bâtiment simulé, sans réseau et en accéléré.

Du lundi au mercredi : tout va bien (recalage de la salle SAR 200). Jeudi dès 7 h : on provoque
une panne et on regarde si le serveur trouve la bonne cause.

    python tests/test_scenarios.py
"""

import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / 'serveur'))

import serveur  # noqa: E402

SALLE = 'SAR 200'


class PontFactice:
    """Remplace l'automate : la consigne est appliquée telle quelle."""
    def __init__(self):
        self.consigne = 'petite'
        self.etat = {'connecte': False}

    def regler(self, consigne=None, personnes=None, **_):
        self.consigne = consigne or self.consigne


def jouer(panne=None, jours=5, jour_panne=3):
    campus = serveur.Campus(None, PontFactice())
    sim = serveur.charger_simulateur('batiment').SimulateurBatiment(
        campus.recevoir, lambda s: campus.salles[s].niveau or 'petite')
    campus.simulation = sim
    campus.t = sim.t
    campus.ajouter_cartes(sim.annuaire())
    debut = datetime.fromtimestamp(sim.t).date()
    vus = {}
    while (datetime.fromtimestamp(sim.t).date() - debut).days < jours:
        sim.pas(10)
        campus.piloter()
        d = datetime.fromtimestamp(sim.t)
        if panne and (d.date() - debut).days >= jour_panne and not sim.salles[SALLE].pannes[panne]:
            sim.salles[SALLE].pannes[panne] = True
        if d.minute % 10 == 0 and d.second < 10:
            etat = campus.salles[SALLE].etat(sim.t)
            for cle, cause in etat['air']['diagnostic'].items():
                if cause['etat'] in ('suspect', 'detecte') and (cle, cause['etat']) not in vus:
                    vus[(cle, cause['etat'])] = d.strftime('%a %Hh%M')
            for a in etat['alertes']:
                cle = ('alerte', a['texte'][:40])
                if cle not in vus and ('badge' in a['texte'] or 'carte' in a['texte'].lower() or 'passage' in a['texte']):
                    vus[cle] = d.strftime('%a %Hh%M') + ' ' + a['texte']
    return campus, vus


def main():
    resultats = {}
    for panne in [None, 'ventilation', 'fenetre', 'derive', 'comptage', 'badgePrete', 'sansBadge']:
        campus, vus = jouer(panne)
        s = campus.salles[SALLE]
        est = s.estimateur
        print(f'\n== {panne or "aucune panne"}  (biais appris {est.biais and round(est.biais, 2)}, '
              f'Wi-Fi : {s.wifi.a:.2f} x appareils {s.wifi.b:+.1f})')
        for cle, quand in vus.items():
            print(f'   {cle} : {quand}')
        resultats[panne] = vus

    # Ce qu'on attend
    def detecte(panne, cause):
        return (cause, 'detecte') in resultats[panne]

    def pretees(panne):
        """Alertes « carte prêtée » différentes vues pendant la semaine."""
        return sum(1 for k, v in resultats[panne].items() if k[0] == 'alerte' and 'prêtée' in str(v))

    # Sans fraude, une alerte peut arriver : la porte rate ~2 % des passages, et si un autre étudiant badge
    # dans les 3 s, ça ressemble à une carte prêtée. C'est « à vérifier » : l'enseignant regarde.
    print(f'\nAlertes « carte prêtée » : {pretees(None)} sans fraude, {pretees("badgePrete")} avec fraude')
    verifs = [
        ('aucune panne : aucune cause détectée', not any(k[1] == 'detecte' for k in resultats[None] if k[0] != 'alerte')),
        ('aucune panne : au plus une fausse « carte prêtée » dans la semaine', pretees(None) <= 1),
        ('ventilation en panne détectée', detecte('ventilation', 'ventilation')),
        ('fenêtre ouverte détectée', detecte('fenetre', 'fenetre')),
        ('dérive du capteur détectée', detecte('derive', 'derive')),
        ('comptage faux détecté', detecte('comptage', 'comptage')),
        ('carte prêtée repérée (plus d\'alertes qu\'en temps normal)', pretees('badgePrete') > pretees(None)),
        ('entrée sans badge repérée', any('sans badge' in str(v) for v in resultats['sansBadge'].values())),
    ]
    print()
    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
