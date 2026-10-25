// Vue directeur de tout l'IUT : boucle principale.
// Si la page est servie par le serveur CampusTwin, elle affiche ses données (capteurs réels ou
// bâtiment simulé par le serveur). Sinon, elle simule elle-même le bâtiment dans le navigateur.

import { creerSimIut, pasIut, allerA, etatLocal, HEURE_DEBUT } from './simulationIut.js';
import { creerVueIut } from './vueIut.js';
import { creerPanneauIut } from './panneauIut.js';

const PAS = 1 / 60;                 // une minute simulée
const NOMS_JOURS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];

const vue = { mode: 'occupation', etage: 'tous', selection: 'SAR 200', vitesse: 300, enPause: false };
let etat = null;                    // dernier état affiché
let serveur = false;

const vue3d = creerVueIut(document.getElementById('vue-iut'), id => { vue.selection = vue.selection === id ? null : id; });

// ---------- source 1 : le serveur ----------

function depuisServeur(d) {
  const salles = {};
  for (const [id, s] of Object.entries(d.salles)) {
    salles[id] = { personnes: s.personnes, source: s.source, co2: s.co2, cours: s.cours, alertes: s.alertes, air: s.air, reel: null };
  }
  return { jour: d.jour, t: d.heure, titre: `${NOMS_JOURS[d.jour]} ${d.date}`, source: 'serveur', salles };
}

async function essayerServeur() {
  try {
    const r = await fetch('/api/etat', { cache: 'no-store' });
    if (r.status === 401) {
      // Servie par le serveur CampusTwin, mais pas connecté : on passe par la page de connexion
      location.href = `/suivi/connexion.html?retour=${encodeURIComponent(location.pathname)}`;
      return false;
    }
    if (!r.ok) return false;           // 403 (enseignant) ou simple serveur web : simulation locale
    const d = await r.json();
    etat = depuisServeur(d);
    const flux = new EventSource('/api/flux');
    flux.onmessage = e => { etat = depuisServeur(JSON.parse(e.data)); };
    document.querySelector('.bandeau').textContent = d.simulation
      ? 'Données du serveur CampusTwin : bâtiment simulé par le serveur (mêmes messages que les vraies cartes). Les salles et les cours de TP1/TP2 sont réels.'
      : 'Données du serveur CampusTwin : capteurs réels.';
    // Le temps est celui du serveur : on cache les boutons de jour et de vitesse
    for (const id of ['jours', 'vitesse-iut', 'pause-iut']) document.getElementById(id).closest('.groupe').hidden = true;
    return true;
  } catch {
    return false;
  }
}

// ---------- source 2 : la simulation du navigateur ----------

const sim = creerSimIut();
allerA(sim, 0, 9.0);                // lundi 9 h

const panneau = creerPanneauIut({
  surSelection: id => { vue.selection = id; },
  surJour: j => allerA(sim, j, Math.max(HEURE_DEBUT, 8.0)),
  surEtage: e => { vue.etage = e; },
  surMode: m => { vue.mode = m; },
  surVitesse: v => { vue.vitesse = v; },
  surPause: () => { vue.enPause = !vue.enPause; },
});

serveur = await essayerServeur();

let derniere = performance.now();
let dernierPanneau = 0;
let reste = 0;

function boucle(maintenant) {
  const dt = Math.min(0.25, (maintenant - derniere) / 1000);
  derniere = maintenant;
  if (!serveur) {
    if (!vue.enPause) {
      reste += (dt * vue.vitesse) / 3600;
      while (reste >= PAS) {
        pasIut(sim, PAS);
        reste -= PAS;
      }
    }
    if (maintenant - dernierPanneau > 300 || !etat) etat = etatLocal(sim);
  }
  vue3d.rendre({ salles: etat.salles, mode: vue.mode, etage: vue.etage, selection: vue.selection, surligne: panneau.surlignees(etat) });
  if (maintenant - dernierPanneau > 300) {
    panneau.mettreAJour(etat, vue);
    dernierPanneau = maintenant;
  }
  requestAnimationFrame(boucle);
}
requestAnimationFrame(boucle);
