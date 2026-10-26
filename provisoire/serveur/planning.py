"""Emploi du temps de chaque jour, avec les changements de salle décidés dans l'interface.

L'emploi du temps (edt.json) donne une semaine type : chaque cours revient le même jour de la
semaine. Quand le directeur accepte de déplacer un cours (proposition du jumeau), le changement
est gardé pour cette date seulement, dans le registre, et s'applique partout : badges, comptage,
air, prévisions, et dans la simulation (les étudiants vont dans la nouvelle salle).
"""

import threading


class Planning:
    def __init__(self, edt, registre=None):
        self.edt = edt
        self.registre = registre
        self.verrou = threading.Lock()
        # (date iso, id du cours) -> salle ; chargé une fois, puis tenu à jour en mémoire
        self.changements = registre.changements() if registre else {}
        self.cache = {}

    def cours_du_jour(self, jour):
        """Cours de cette date (objet date), salles changées comprises."""
        cle = jour.isoformat()
        with self.verrou:
            if cle not in self.cache:
                liste = []
                for c in self.edt['cours']:
                    if c['jour'] != jour.weekday():
                        continue
                    salle = self.changements.get((cle, c['id']))
                    if salle and salle != c['salle']:
                        c = {**c, 'salle': salle, 'salle_prevue': c['salle']}
                    liste.append(c)
                if len(self.cache) > 7:
                    self.cache.clear()
                self.cache[cle] = liste
            return self.cache[cle]

    def changer_salle(self, jour, cours, salle, auteur, t):
        avant = next((c['salle'] for c in self.edt['cours'] if c['id'] == cours), None)
        if self.registre:
            self.registre.changer_salle(jour, cours, avant, salle, auteur, t)
        with self.verrou:
            self.changements[(jour.isoformat(), cours)] = salle
            self.cache = {}
