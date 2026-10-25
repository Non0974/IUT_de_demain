"""Enregistrement de tous les messages des capteurs (SQLite, fourni avec Python)."""

import json
import sqlite3
import threading


class Stockage:
    def __init__(self, chemin):
        self.base = sqlite3.connect(chemin, check_same_thread=False)
        self.verrou = threading.Lock()
        with self.verrou:
            self.base.execute('CREATE TABLE IF NOT EXISTS messages (t REAL, salle TEXT, type TEXT, donnees TEXT)')
            self.base.execute('CREATE INDEX IF NOT EXISTS messages_t ON messages (t)')
            self.base.commit()
        self.a_ecrire = 0

    def enregistrer(self, message):
        with self.verrou:
            self.base.execute('INSERT INTO messages VALUES (?, ?, ?, ?)',
                              (message.get('t'), message.get('salle'), message.get('type'), json.dumps(message)))
            self.a_ecrire += 1
            if self.a_ecrire >= 200:      # on regroupe les écritures sur le disque
                self.base.commit()
                self.a_ecrire = 0

    def fermer(self):
        with self.verrou:
            self.base.commit()
            self.base.close()
