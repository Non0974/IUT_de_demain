// Salles du site de Sarcelles. Noms et nombres de places tirés des emplois du temps CELCAT
// (2025-2026 et 2026-2027).
// La disposition est SCHÉMATIQUE : on n'a pas encore le vrai plan. Pour la corriger, il suffit
// de changer l'ordre ou le côté des salles ici (le plan d'évacuation affiché dans les couloirs suffit).
// Pour ajouter une salle ou changer ses places, modifier donnees/salles.json.

import { chargerJson } from './charger.js';

// Liste des salles : jumeau3d/donnees/salles.json (le serveur lit le même fichier)
const donnees = await chargerJson(new URL('../../donnees/salles.json', import.meta.url));

export const HAUTEUR_SALLE = donnees.hauteur;   // m
export const PROFONDEUR = 7.5;                  // m, profondeur des salles de chaque côté du couloir
export const COULOIR = 2.4;                     // m
const ESPACE = 0.3;                             // m entre deux salles

export const SALLES = donnees.salles.map(s => ({ ...s }));

export const ETAGES = [...new Set(SALLES.map(s => s.etage))].sort();

export function nomEtage(etage) {
  return etage === 0 ? 'rez-de-chaussée' : etage === 1 ? '1er étage' : `${etage}e étage`;
}

function numero(salle) {
  return Number((salle.id.match(/\d+/) || ['0'])[0]);   // « SAR 047-049 » -> 47, « SAR Amphi 1 » -> 1
}

// Place les salles : numéros pairs d'un côté du couloir, impairs de l'autre, dans l'ordre des numéros
function disposer() {
  let longueurMax = 0;
  for (const etage of ETAGES) {
    for (const cote of [0, 1]) {
      let x = 0;
      const rangee = SALLES.filter(s => s.etage === etage && numero(s) % 2 === cote)
        .sort((a, b) => numero(a) - numero(b));
      for (const s of rangee) {
        s.largeur = Math.max(6.5, s.surface / PROFONDEUR);   // assez large pour son étiquette
        s.profondeur = PROFONDEUR;
        s.volume = s.surface * HAUTEUR_SALLE;
        s.x = x + s.largeur / 2;
        s.z = (cote === 0 ? 1 : -1) * (COULOIR / 2 + PROFONDEUR / 2);
        x += s.largeur + ESPACE;
      }
      longueurMax = Math.max(longueurMax, x);
    }
  }
  // On centre le bâtiment sur x = 0
  for (const s of SALLES) s.x -= longueurMax / 2;
  return longueurMax;
}

export const LONGUEUR_BATIMENT = disposer();
