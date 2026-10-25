// Interface de suivi des classes : menu, horloge du serveur et navigation entre les pages.
// Chaque page est une fonction async (zone, ctx) ; si elle a une propriété "rafraichir" (ms),
// elle est redessinée régulièrement (données en direct), sauf pendant une modification.

import { api, allerConnexion } from './api.js';
import { echapper, heure, dateLongue } from './ui.js';
import { vueTableau } from './vues/tableau.js';
import { vueSeances } from './vues/seances.js';
import { vueSeance } from './vues/seance.js';
import { vueClasses } from './vues/classes.js';
import { vueClasse } from './vues/classe.js';
import { vueEtudiant } from './vues/etudiant.js';

const ROUTES = [
  [/^\/?$/, 'tableau', vueTableau],
  [/^\/seances$/, 'seances', vueSeances],
  [/^\/seance\/(.+)$/, 'seances', vueSeance],
  [/^\/classes$/, 'classes', vueClasses],
  [/^\/classe\/(.+)$/, 'classes', vueClasse],
  [/^\/etudiant\/(.+)$/, 'classes', vueEtudiant],
];

const ROLES = { directeur: 'Directeur des études', scolarite: 'Scolarité', enseignant: 'Enseignant' };

let utilisateur = null;
let minuteur = null;
let numeroRendu = 0;
let info = null;

function lireAdresse() {
  const [chemin, requete] = location.hash.slice(1).split('?');
  return { chemin: chemin || '/', query: new URLSearchParams(requete || '') };
}

async function horloge() {
  try {
    info = await api('/api/info');
    document.getElementById('horloge-date').textContent = dateLongue(info.date);
    document.getElementById('horloge-heure').textContent = heure(info.heure);
    document.getElementById('simulation').hidden = !info.simulation;
  } catch { /* le serveur ne répond pas : on réessaiera */ }
}

async function naviguer() {
  clearInterval(minuteur);
  const { chemin, query } = lireAdresse();
  let route = null;
  let morceaux = [];
  for (const r of ROUTES) {
    const m = chemin.match(r[0]);
    if (m) { route = r; morceaux = m.slice(1).map(decodeURIComponent); break; }
  }
  if (!route) { location.hash = '#/'; return; }
  const [, rubrique, vue] = route;
  document.querySelectorAll('.menu nav a[data-rubrique]').forEach(a => a.classList.toggle('actif', a.dataset.rubrique === rubrique));

  // Zone neuve à chaque page : les écouteurs de la page précédente disparaissent avec l'ancienne
  const ancienne = document.getElementById('contenu');
  const zone = ancienne.cloneNode(false);
  ancienne.replaceWith(zone);
  zone.innerHTML = '<p class="chargement">Chargement…</p>';
  zone.dataset.html = '';
  zone.dataset.vue = '';
  const numero = ++numeroRendu;
  const ctx = {
    utilisateur,
    query,
    params: morceaux,
    info: () => info,
    titre: t => {
      document.getElementById('titre').textContent = t;
      document.title = `${t} — CampusTwin`;
    },
    redessiner: () => executer(),
  };
  const executer = async () => {
    if (numero !== numeroRendu) return;                              // on a changé de page entre-temps
    if (document.getElementById('dialogue-statut').open) return;      // pas pendant une modification
    try {
      await vue(zone, ctx);
    } catch (e) {
      if (e.code === 401) return;
      zone.innerHTML = `<div class="carte"><h2>Impossible d'afficher cette page</h2><p>${echapper(e.message)}</p><p><a href="#/">Retour au tableau de bord</a></p></div>`;
      zone.dataset.html = '';
    }
  };
  await executer();
  if (numero === numeroRendu) zone.focus({ preventScroll: true });
  if (vue.rafraichir) minuteur = setInterval(() => { if (!document.hidden) executer(); }, vue.rafraichir);
}

async function demarrer() {
  try {
    utilisateur = await api('/api/moi');
  } catch (e) {
    if (e.code !== 401) {           // 401 : api() renvoie déjà vers la connexion
      document.getElementById('contenu').innerHTML = `<div class="carte"><h2>Serveur CampusTwin introuvable</h2>
        <p>Cette interface lit le registre des présences du serveur. Lancez-le avec <code>python serveur/serveur.py --simulation</code>
        (ou <code>lancer.bat</code>), puis ouvrez <a href="http://localhost:8000">http://localhost:8000</a>.</p></div>`;
    }
    return;
  }
  document.getElementById('utilisateur-nom').textContent = utilisateur.nom;
  document.getElementById('utilisateur-role').textContent = ROLES[utilisateur.role] || utilisateur.role;
  if (utilisateur.role === 'enseignant') {
    document.querySelectorAll('.direction-seulement').forEach(e => { e.hidden = true; });
  }
  document.getElementById('deconnexion').addEventListener('click', async () => {
    await api('/api/deconnexion', {}).catch(() => {});
    allerConnexion();
  });
  window.addEventListener('hashchange', naviguer);
  await horloge();
  setInterval(horloge, 5000);
  naviguer();
}

demarrer();
