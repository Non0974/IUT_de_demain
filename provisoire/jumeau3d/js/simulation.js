// Simulation physique d'une salle de cours : occupation, CO2, ventilation et pannes.
// Elle remplace les vrais capteurs tant que le matériel n'est pas arrivé.

export const SALLE = { longueur: 10, largeur: 7, hauteur: 2.6 };
SALLE.volume = SALLE.longueur * SALLE.largeur * SALLE.hauteur; // m3 (182 m3)

export const C_EXT = 420;            // ppm, air extérieur
export const G_MODELE = 0.018;       // m3/h de CO2 par personne assise (valeur utilisée par le modèle)
const G_REEL = 0.0195;               // valeur "vraie" de la simulation, un peu différente exprès
export const INFILTRATION = 25;      // m3/h, fuites d'air quand tout est fermé
export const DEBITS = { arret: 0, petite: 350, grande: 700 }; // m3/h fournis par le ventilateur
const DEBIT_FENETRE = 450;           // m3/h quand la fenêtre est ouverte
const T_INT = 20;                    // °C
const T_FENETRE_OUVERTE = 13;        // °C vers lesquels tend le capteur près de la fenêtre

// Emploi du temps : [début, fin, effectif] en heures décimales
export const EMPLOI_DU_TEMPS = [
  [8.0, 10.0, 28],
  [10.25, 12.25, 24],
  [13.5, 15.5, 30],
  [15.75, 17.75, 18],
];
export const HEURE_DEBUT = 7.0;
export const HEURE_FIN = 21.0;

const ARRIVEE_AVANT = 6 / 60;   // les étudiants arrivent de 6 min avant...
const ARRIVEE_APRES = 3 / 60;   // ...à 3 min après le début du cours
const DUREE_SORTIE = 4 / 60;    // ils sortent en 4 min
const PURGE = 2.75;             // h de ventilation "petite" après le dernier cours (décroissance + mesure de nuit)

function bruit(sigma) {
  // Bruit gaussien (Box-Muller)
  const u = 1 - Math.random();
  const v = Math.random();
  return sigma * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function clamp01(x) {
  return Math.min(1, Math.max(0, x));
}

// Nombre réel de personnes dans la salle à l'heure t
export function occupationReelle(t) {
  for (const [debut, fin, effectif] of EMPLOI_DU_TEMPS) {
    const entree = clamp01((t - (debut - ARRIVEE_AVANT)) / (ARRIVEE_AVANT + ARRIVEE_APRES));
    const sortie = clamp01((t - fin) / DUREE_SORTIE);
    if (t >= debut - ARRIVEE_AVANT && t <= fin + DUREE_SORTIE) {
      return Math.round(effectif * entree * (1 - sortie));
    }
  }
  return 0;
}

export function coursEnCours(t) {
  return EMPLOI_DU_TEMPS.find(([debut, fin]) => t >= debut && t < fin) || null;
}

export function creerSimulation() {
  return {
    t: HEURE_DEBUT,
    jour: 1,
    C: C_EXT + 30,              // ppm, valeur vraie
    T_fenetre: T_INT,
    N_reel: 0,
    N_mesure: 0,
    niveau: 'arret',            // commande du ventilateur
    finDernierCours: null,
    // badgePrete et sansBadge ne touchent pas l'air : ils servent à tester l'émargement
    pannes: { ventilation: false, fenetre: false, derive: false, comptage: false, badgePrete: false, sansBadge: false },
    mesures: { C: C_EXT, T_fenetre: T_INT },
    Q_reel: INFILTRATION,
  };
}

// Logique de commande du ventilateur (ce que fera l'automate)
function commandeVentilation(sim) {
  const t = sim.t;
  const dernierCours = EMPLOI_DU_TEMPS[EMPLOI_DU_TEMPS.length - 1];
  if (sim.N_mesure > 0) return sim.N_mesure <= 15 ? 'petite' : 'grande';
  // Salle vide : on garde une petite ventilation entre les cours, et une purge après le dernier
  if (t >= EMPLOI_DU_TEMPS[0][0] - ARRIVEE_AVANT && t <= dernierCours[1] + PURGE) return 'petite';
  return 'arret';
}

// Avance la simulation de dt heures
export function pas(sim, dt) {
  sim.t += dt;
  if (sim.t >= HEURE_FIN) {
    sim.t = HEURE_DEBUT;
    sim.jour += 1;
  }

  sim.N_reel = occupationReelle(sim.t);
  sim.N_mesure = sim.pannes.comptage ? Math.round(sim.N_reel * 1.5) : sim.N_reel;
  sim.niveau = commandeVentilation(sim);

  const santeVentilateur = sim.pannes.ventilation ? 0.15 : 1;
  sim.Q_reel = DEBITS[sim.niveau] * santeVentilateur + INFILTRATION
    + (sim.pannes.fenetre ? DEBIT_FENETRE : 0);

  // Bilan de masse du CO2 (en ppm par heure)
  const production = (sim.N_reel * G_REEL / SALLE.volume) * 1e6;
  const renouvellement = (sim.Q_reel / SALLE.volume) * (sim.C - C_EXT);
  sim.C += (production - renouvellement) * dt;

  // Température près de la fenêtre
  const cibleT = sim.pannes.fenetre ? T_FENETRE_OUVERTE : T_INT;
  sim.T_fenetre += (cibleT - sim.T_fenetre) * clamp01(dt / (5 / 60));

  // Ce que mesurent les capteurs
  const derive = sim.pannes.derive ? 150 : 0;
  sim.mesures = {
    C: sim.C + derive + bruit(8),
    T_fenetre: sim.T_fenetre + bruit(0.1),
  };
}
