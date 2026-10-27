// Cartes étudiantes : on badge une carte sur un lecteur, elle apparaît ici, et on dit à qui elle est.
// Le serveur ne connaît que l'empreinte de la carte (jamais son numéro) ; les noms restent sur le PC
// du serveur (serveur/cartes.json, pas sur GitHub).

import { api } from '../api.js';
import { afficher, echapper, heure } from '../ui.js';

const fin = empreinte => `••••${echapper(empreinte.slice(-4))}`;
let message = null;                  // dernier résultat, gardé quelques secondes malgré le rafraîchissement

function choixPorteur(d) {
  const groupes = d.groupes.map(g => `<optgroup label="${echapper(g.nom)}">${g.etudiants.map(e =>
    `<option value="${echapper(e.id)}">${echapper(e.id)}${e.nom ? ` — ${echapper(e.nom)}` : ''}${e.carte ? ' (a déjà une carte)' : ''}</option>`).join('')}</optgroup>`);
  const enseignants = d.enseignants.length ? `<optgroup label="Enseignants">${d.enseignants.map(e =>
    `<option value="${echapper(e.id)}">${echapper(e.id)}${e.carte ? ' (a déjà une carte)' : ''}</option>`).join('')}</optgroup>` : '';
  return `<option value="">Choisir…</option>${groupes.join('')}${enseignants}`;
}

export async function vueCartes(zone, ctx) {
  // Pas de rafraîchissement pendant une saisie : on perdrait le nom en cours d'écriture
  if (zone.contains(document.activeElement) && document.activeElement.matches('input, select')) return;
  ctx.titre('Cartes étudiantes');
  const [d, liste] = await Promise.all([api('/api/cartes/inconnues'), api('/api/cartes/liste')]);

  if (!zone.dataset.ecoute) {
    zone.dataset.ecoute = '1';
    zone.addEventListener('submit', async e => {
      const f = e.target.closest('form[data-empreinte]');
      if (!f) return;
      e.preventDefault();
      try {
        await api('/api/cartes/associer', { empreinte: f.dataset.empreinte, etudiant: f.elements.qui.value, nom: f.elements.nom.value });
        message = { classe: 'ok', texte: `Carte enregistrée pour ${f.elements.qui.value}.`, t: Date.now() };
      } catch (err) {
        message = { classe: 'erreur', texte: err.message, t: Date.now() };
      }
      document.activeElement.blur();
      await ctx.redessiner();
    });
    zone.addEventListener('click', async e => {
      const b = e.target.closest('button[data-retirer]');
      if (!b) return;
      b.disabled = true;
      await api('/api/cartes/retirer', { empreinte: b.dataset.retirer }).catch(() => {});
      await ctx.redessiner();
    });
  }

  const inconnues = d.cartes.length ? d.cartes.map(c => `<form class="carte ligne-carte" data-empreinte="${echapper(c.empreinte)}">
      <div><b>Carte ${fin(c.empreinte)}</b><span class="sous">badgée en ${echapper(c.salle)} à ${heure(c.heure)}</span></div>
      <label>À qui ? <select name="qui" required>${choixPorteur(d)}</select></label>
      <label>Nom <span class="sous">(facultatif)</span> <input name="nom" maxlength="60" autocomplete="off"></label>
      <button type="submit" class="bouton principal-bouton">Enregistrer</button>
    </form>`).join('')
    : '<p class="vide">Aucune carte en attente. Badgez une carte sur un lecteur pour la voir ici.</p>';

  const lignes = liste.cartes.map(c => `<tr>
      <td class="nowrap"><b>${echapper(c.id)}</b></td><td>${echapper(c.nom || '—')}</td>
      <td>${c.groupe === 'enseignant' ? 'Enseignant' : echapper(c.groupe)}</td><td class="sous">${fin(c.empreinte)}</td>
      <td><button type="button" class="bouton petit" data-retirer="${echapper(c.empreinte)}">Retirer</button></td></tr>`).join('');

  const avis = message && Date.now() - message.t < 6000 ? message : null;
  afficher(zone, `
    <p id="message-cartes" class="message${avis ? ` ${avis.classe}` : ''}" role="status">${avis ? echapper(avis.texte) : ''}</p>
    <section class="section">
      <h2 class="titre-section">Cartes à enregistrer</h2>
      <div class="liste-cartes">${inconnues}</div>
    </section>
    <section class="section">
      <h2 class="titre-section">Cartes enregistrées (${liste.cartes.length})</h2>
      ${liste.cartes.length ? `<div class="tableau-conteneur"><table class="liste">
        <thead><tr><th>Étudiant</th><th>Nom</th><th>Groupe</th><th>Carte</th><th></th></tr></thead>
        <tbody>${lignes}</tbody></table></div>` : '<p class="vide">Aucune carte enregistrée pour la classe.</p>'}
      <p class="sous">Une nouvelle carte remplace l'ancienne. Le serveur garde une empreinte de la carte, pas son numéro.
        Les noms restent sur ce PC (serveur/cartes.json).</p>
    </section>`);
}
vueCartes.rafraichir = 3000;
