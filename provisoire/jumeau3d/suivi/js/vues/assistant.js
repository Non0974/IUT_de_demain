// Assistant IA : on pose une question en français, il répond avec les données de CampusTwin.
// Les noms ne partent jamais vers l'IA : le serveur envoie des pseudonymes (ETU-001, « Enseignant A »)
// et remet les vrais noms au retour. Ici, chaque ETU-… devient un lien vers la fiche de l'étudiant.

import { api } from '../api.js';
import { echapper } from '../ui.js';

function enrichir(html, noms) {
  return html
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/ETU-\d{3,}/g, j => (noms[j]
      ? `<a href="#/etudiant/${encodeURIComponent(noms[j].id)}">${echapper(noms[j].nom)}</a>` : j));
}

// Texte de l'IA -> HTML : paragraphes, listes, gras. Tout est échappé avant.
function rendre(texte, noms = {}) {
  let html = '';
  let liste = null;
  for (const brute of texte.split('\n')) {
    const ligne = brute.trim().replace(/^#+\s*/, '');
    const puce = ligne.match(/^([-•*]|\d+[.)])\s+/);
    const type = puce ? (/\d/.test(puce[1]) ? 'ol' : 'ul') : null;
    if (liste && liste !== type) { html += `</${liste}>`; liste = null; }
    if (!ligne) continue;
    if (type && !liste) { html += `<${type}>`; liste = type; }
    const contenu = enrichir(echapper(puce ? ligne.slice(puce[0].length) : ligne), noms);
    html += type ? `<li>${contenu}</li>` : `<p>${contenu}</p>`;
  }
  return html + (liste ? `</${liste}>` : '');
}

function bulleQuestion(e) {
  const envoye = e.envoye && e.envoye !== e.question
    ? `<span class="envoye">Envoyé à l'IA : « ${echapper(e.envoye)} »</span>` : '';
  return `<div class="msg msg-question"><p>${echapper(e.question)}</p>${envoye}</div>`;
}

function bulleReponse(e) {
  const consulte = e.outils.length ? `Données lues : ${e.outils.map(echapper).join(', ')}` : 'Aucune donnée lue';
  return `<div class="msg msg-reponse">${rendre(e.texte, e.noms)}
    <span class="pied-msg">${consulte} · ${String(e.duree).replace('.', ',')} s</span></div>`;
}

const VIDE = `<p class="vide-assistant">Posez une question sur les présences, les salles ou l'air.</p>`;

export async function vueAssistant(zone, ctx) {
  ctx.titre('Assistant IA');
  const etat = await api('/api/assistant');
  const actif = etat.disponible ? '' : 'disabled';
  const bandeau = !etat.disponible
    ? `<div class="message erreur">Assistant hors ligne : ${echapper(etat.raison)}</div>`
    : etat.raison ? `<div class="message attention">${echapper(etat.raison)}</div>` : '';
  zone.innerHTML = `${bandeau}
    <section class="carte discussion" aria-label="Conversation avec l'assistant">
      <div id="fil" class="fil" aria-live="polite"></div>
      <div id="suggestions" class="suggestions">${etat.suggestions.map(q =>
        `<button type="button" class="suggestion" data-question="${echapper(q)}" ${actif}>${echapper(q)}</button>`).join('')}</div>
      <form id="formulaire-question" class="zone-question">
        <textarea id="question" rows="2" maxlength="1000" aria-label="Votre question"
          placeholder="Ex. : qui est absent en SAR 109 ce matin ?" ${actif}></textarea>
        <div class="actions-question">
          <button type="button" id="nouvelle" class="bouton discret petit">Nouvelle conversation</button>
          <button type="submit" id="envoyer" class="bouton principal-bouton" ${actif}>Envoyer</button>
        </div>
      </form>
    </section>
    <p class="note-confidentialite">Les noms ne sont pas envoyés à l'IA (ETU-001, Enseignant A…), ni les motifs d'absence.
      Elle ne modifie rien. Modèle : ${echapper(etat.modele)}.</p>`;
  zone.dataset.html = '';

  const fil = zone.querySelector('#fil');
  const champ = zone.querySelector('#question');
  const bouton = zone.querySelector('#envoyer');
  const suggestions = zone.querySelector('#suggestions');
  let enCours = false;

  const descendre = () => { fil.scrollTop = fil.scrollHeight; };
  const montrer = conversation => {
    fil.innerHTML = conversation.length ? conversation.map(e => bulleQuestion(e) + bulleReponse(e)).join('') : VIDE;
    suggestions.hidden = conversation.length > 0;
    descendre();
  };
  montrer(etat.conversation);

  async function envoyer(question) {
    question = question.trim();
    if (!question || enCours || !etat.disponible) return;
    enCours = true;
    bouton.disabled = true;
    champ.value = '';
    suggestions.hidden = true;
    fil.querySelector('.vide-assistant')?.remove();
    fil.insertAdjacentHTML('beforeend', `${bulleQuestion({ question })}
      <div class="msg msg-reponse attente">Recherche<span class="points" aria-hidden="true"></span></div>`);
    descendre();
    const attente = fil.lastElementChild;
    try {
      const e = await api('/api/assistant', { question });
      attente.previousElementSibling.outerHTML = bulleQuestion(e);       // avec ce qui est vraiment parti
      attente.outerHTML = bulleReponse(e);
    } catch (err) {
      attente.outerHTML = `<div class="msg msg-erreur">${echapper(err.message)}</div>`;
      champ.value = question;                                            // pour réessayer
    } finally {
      enCours = false;
      bouton.disabled = false;
      descendre();
      champ.focus();
    }
  }

  zone.querySelector('#formulaire-question').addEventListener('submit', e => {
    e.preventDefault();
    envoyer(champ.value);
  });
  champ.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {                               // Maj+Entrée : retour à la ligne
      e.preventDefault();
      envoyer(champ.value);
    }
  });
  suggestions.addEventListener('click', e => {
    const b = e.target.closest('button[data-question]');
    if (b) envoyer(b.dataset.question);
  });
  zone.querySelector('#nouvelle').addEventListener('click', async () => {
    if (enCours) return;
    await api('/api/assistant', { nouvelle: true });
    montrer([]);
    champ.focus();
  });
  if (etat.disponible) champ.focus();
}
