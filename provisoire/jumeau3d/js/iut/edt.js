// Emploi du temps de la semaine du lundi 16 au vendredi 20 novembre 2026.
// Les cours de la classe GEIIS BUT3 ESE FA S5 (TD1 = TP1 + TP2) viennent de CELCAT (donc réels).
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
