// Tickets : il manque une table, des feutres, le vidéoprojecteur ne marche pas...
// Un enseignant signale le problème ; le serveur ajoute l'échéance (prochain cours dans la salle),
// l'urgence, le moment où la salle est libre et les places perdues. Le service technique s'en occupe.

import { api } from '../api.js';
import { afficher, echapper, tuile } from '../ui.js';

const URGENCES = {
  urgent: { libelle: 'Urgent', classe: 'absent' },
  'avant le prochain cours': { libelle: 'Avant le prochain cours', classe: 'retard' },
  'pas pressé': { libelle: 'Pas pressé', classe: 'attendu' },
};
const ETAGES = ['Rez-de-chaussée', '1er étage', '2e étage', '3e étage'];
let message = null;                  // dernier résultat, gardé quelques secondes malgré le rafraîchissement

function etiquetteUrgence(x) {
  if (x.statut === 'résolu') return '<span class="statut s-present">Résolu</span>';
  const u = URGENCES[x.urgence] || URGENCES['pas pressé'];
  return `<span class="statut s-${u.classe}">${u.libelle}</span>`;
}

function quand(t, aujourdhui) {
  const d = new Date(t * 1000);
  const jour = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const h = `${String(d.getHours()).padStart(2, '0')}h${String(d.getMinutes()).padStart(2, '0')}`;
  return jour === aujourdhui ? `à ${h}` : `le ${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')} à ${h}`;
}

function formulaire(d, salleChoisie) {
  const parEtage = {};
  d.salles.forEach(s => { (parEtage[s.etage] ||= []).push(s); });
  const salles = Object.keys(parEtage).sort().map(e => `<optgroup label="${ETAGES[e] || `Étage ${e}`}">${parEtage[e].map(s =>
    `<option value="${echapper(s.id)}"${s.id === salleChoisie ? ' selected' : ''}>${echapper(s.id)} (${s.places} places)</option>`).join('')}</optgroup>`).join('');
  const objets = Object.entries(d.objets).map(([cle, o]) =>
    `<option value="${cle}" data-quantite="${o.quantite ? 1 : 0}">${echapper(o.nom)}</option>`).join('');
  return `<form class="carte formulaire-ticket" id="signaler">
      <h2 class="titre-section">Signaler un problème</h2>
      <label>Salle <select name="salle" required><option value="">Choisir…</option>${salles}</select></label>
      <label>Problème <select name="objet">${objets}</select></label>
      <label id="champ-quantite">Nombre <input type="number" name="quantite" min="1" max="30" value="1"></label>
      <label>Précision (facultatif)
        <input name="detail" maxlength="300" autocomplete="off" placeholder="Ex. : les feutres bleus ne marchent plus"></label>
      <button type="submit" class="bouton principal-bouton">Envoyer</button>
    </form>`;
}

function carteTicket(x, d, aujourdhui) {
  const actions = [];
  if (d.peut_changer) {
    if (x.statut === 'ouvert') actions.push(`<button type="button" class="bouton petit" data-ticket="${x.id}" data-statut="en cours">Je m'en occupe</button>`);
    if (x.statut !== 'résolu') actions.push(`<button type="button" class="bouton petit principal-bouton" data-ticket="${x.id}" data-statut="résolu">Résolu</button>`);
    else actions.push(`<button type="button" class="bouton petit" data-ticket="${x.id}" data-statut="ouvert">Rouvrir</button>`);
  } else if (x.mien && x.statut !== 'résolu') {
    actions.push(`<button type="button" class="bouton petit" data-ticket="${x.id}" data-statut="résolu">C'est réglé</button>`);
  }
  const suivi = x.suivi.slice(1).map(s => `<li>${quand(s.t, aujourdhui)}, ${echapper(s.auteur)}
      ${s.statut ? `: ${s.statut === 'ouvert' ? 'rouvert' : echapper(s.statut)}` : ''}${s.texte ? ` : ${echapper(s.texte)}` : ''}</li>`).join('');
  const auteur = x.source === 'jumeau' ? 'Ouvert par CampusTwin' : `Signalé par ${echapper(x.auteur)}`;
  const aFaire = x.statut === 'résolu' ? '' : `<p>${x.echeance
    ? `À faire ${x.echeance.maintenant ? 'tout de suite' : `avant ${echapper(x.echeance.texte)}`}. ` : ''}${echapper(x.raison)}</p>
      ${x.creneau ? `<p class="sous">${echapper(x.creneau.texte)}</p>` : ''}
      ${x.places_perdues ? `<p class="sous">${x.places_perdues} place${x.places_perdues > 1 ? 's' : ''} en moins : ${x.places_restantes} au lieu de ${x.places}.</p>` : ''}`;
  return `<article class="carte ticket">
      <div class="entete"><b>${echapper(x.salle)} : ${echapper(x.titre)}</b>${etiquetteUrgence(x)}</div>
      ${x.detail && x.objet !== 'autre' ? `<p class="detail">${echapper(x.detail)}</p>` : ''}
      ${aFaire}
      <p class="sous">${auteur} ${quand(x.cree, aujourdhui)}, service ${echapper(x.service_nom.toLowerCase())}.${x.statut === 'en cours' ? ' Pris en charge.' : ''}</p>
      ${suivi ? `<details class="suivi-ticket"><summary>Suivi (${x.suivi.length - 1})</summary><ul>${suivi}</ul></details>` : ''}
      <form class="commentaire" data-commenter="${x.id}">
        <input name="texte" maxlength="300" autocomplete="off" placeholder="Commentaire" aria-label="Commentaire sur le ticket ${x.id}">
        <button type="submit" class="bouton petit">Ajouter</button>
      </form>
      ${actions.length ? `<div class="actions">${actions.join('')}</div>` : ''}
    </article>`;
}

export async function vueTickets(zone, ctx) {
  // Pas de rafraîchissement pendant une saisie : on perdrait ce qui est en cours d'écriture
  if (zone.contains(document.activeElement) && document.activeElement.matches('input, select, textarea')) return;
  ctx.titre('Tickets');
  const d = await api('/api/tickets');
  const aujourdhui = ctx.info()?.date;
  const resolus = ctx.query.get('vue') === 'resolus';
  const service = ctx.query.get('service') || '';
  const majQuantite = () => {
    const choix = zone.querySelector('#signaler select[name=objet]');
    zone.querySelector('#champ-quantite').hidden = choix.selectedOptions[0]?.dataset.quantite !== '1';
  };

  if (!zone.dataset.ecoute) {
    zone.dataset.ecoute = '1';
    zone.addEventListener('change', e => { if (e.target.name === 'objet') majQuantite(); });
    zone.addEventListener('submit', async e => {
      e.preventDefault();
      const f = e.target;
      try {
        if (f.id === 'signaler') {
          const objet = f.elements.objet.value;
          const r = await api('/api/tickets', { salle: f.elements.salle.value, objet, detail: f.elements.detail.value,
            quantite: d.objets[objet]?.quantite ? Number(f.elements.quantite.value) : null });
          message = { classe: 'ok', t: Date.now(), texte: r.deja ? 'Déjà signalé : ajouté au ticket existant.' : 'Ticket envoyé.' };
          f.reset();
          majQuantite();
        } else if (f.dataset.commenter) {
          if (!f.elements.texte.value.trim()) return;
          await api('/api/tickets/changer', { id: Number(f.dataset.commenter), texte: f.elements.texte.value });
          message = null;
        }
      } catch (err) {
        message = { classe: 'erreur', texte: err.message, t: Date.now() };
      }
      document.activeElement.blur();
      await ctx.redessiner();
    });
    zone.addEventListener('click', async e => {
      const b = e.target.closest('button[data-statut]');
      if (!b) return;
      b.disabled = true;
      try {
        await api('/api/tickets/changer', { id: Number(b.dataset.ticket), statut: b.dataset.statut });
      } catch (err) {
        message = { classe: 'erreur', texte: err.message, t: Date.now() };
      }
      await ctx.redessiner();
    });
  }

  const aFaire = d.tickets.filter(x => x.statut !== 'résolu');
  const finis = d.tickets.filter(x => x.statut === 'résolu');
  const visibles = (resolus ? finis : aFaire).filter(x => !service || x.service === service);
  const perdues = aFaire.reduce((n, x) => n + x.places_perdues, 0);
  const urgents = aFaire.filter(x => x.urgence === 'urgent').length;
  const tuiles = [
    tuile(aFaire.length, 'tickets ouverts', `dont ${aFaire.filter(x => x.statut === 'en cours').length} pris en charge`),
    tuile(urgents, `urgent${urgents > 1 ? 's' : ''}`, '', urgents ? 'alerte' : ''),
    tuile(perdues, `place${perdues > 1 ? 's' : ''} en moins`),
    tuile(finis.length, `résolu${finis.length > 1 ? 's' : ''} cette semaine`),
  ];
  const lien = (vue, svc) => `#/tickets?${new URLSearchParams({ ...(vue ? { vue } : {}), ...(svc ? { service: svc } : {}) })}`;
  const services = `<select id="filtre-service" aria-label="Service">
      <option value="">Tous les services</option>${Object.entries(d.services).map(([k, v]) =>
        `<option value="${k}"${k === service ? ' selected' : ''}>${echapper(v)}</option>`).join('')}</select>`;
  const avis = message && Date.now() - message.t < 6000 ? message : null;

  // Le formulaire est dessiné une fois : seuls les chiffres et la liste se mettent à jour
  if (!zone.querySelector('#signaler')) {
    zone.innerHTML = `<p class="message" id="message-tickets" role="status"></p>
      <section class="section" id="tuiles-tickets"></section>
      <div class="deux-colonnes colonnes-tickets">
        <section class="section" id="liste-tickets"></section>
        <section class="section">${formulaire(d, ctx.query.get('salle') || '')}
          <p class="note">Une table manquante compte pour 2 places, une chaise ou un poste pour 1.
            CampusTwin ouvre aussi un ticket quand il détecte une panne de ventilation ou de capteur.</p>
        </section>
      </div>`;
    majQuantite();
  }
  const zoneMessage = zone.querySelector('#message-tickets');
  zoneMessage.className = `message${avis ? ` ${avis.classe}` : ''}`;
  zoneMessage.textContent = avis ? avis.texte : '';
  afficher(zone.querySelector('#tuiles-tickets'), `<div class="grille tuiles">${tuiles.join('')}</div>`);
  const liste = zone.querySelector('#liste-tickets');
  afficher(liste, `
    <div class="barre-outils">
      <a class="bouton${resolus ? '' : ' principal-bouton'}" href="${lien('', service)}">Ouverts (${aFaire.length})</a>
      <a class="bouton${resolus ? ' principal-bouton' : ''}" href="${lien('resolus', service)}">Résolus (${finis.length})</a>
      <span class="espace"></span>${services}
    </div>
    ${visibles.length ? `<div class="liste-tickets">${visibles.map(x => carteTicket(x, d, aujourdhui)).join('')}</div>`
      : `<p class="vide">${resolus ? 'Aucun ticket résolu cette semaine.' : 'Aucun ticket ouvert.'}</p>`}`);
  const filtre = liste.querySelector('#filtre-service');
  filtre.onchange = () => { location.hash = lien(resolus ? 'resolus' : '', filtre.value); };
}
vueTickets.rafraichir = 10000;
