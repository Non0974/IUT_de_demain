// Emploi du temps de la semaine 11 (du lundi 9 au vendredi 13 mars 2026).
// Les cours des groupes GEIIS BUT FI S4 TP1 et TP2 sont recopiés des PDF CELCAT (donc réels).
// Les autres groupes qui utilisent les salles ne sont pas connus : on les a complétés avec des cours
// simulés, marqués reel: false.

import { chargerJson } from './charger.js';

// Les cours (réels et simulés) sont dans jumeau3d/donnees/edt.json, lu aussi par le serveur
const donnees = await chargerJson(new URL('../../donnees/edt.json', import.meta.url));

export const JOURS = donnees.jours;
export const GROUPES = donnees.groupes;
export const COURS = donnees.cours;

export function heureTexte(t) {
  const minutes = Math.round(t * 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, '0')}h${String(m).padStart(2, '0')}`;
}
