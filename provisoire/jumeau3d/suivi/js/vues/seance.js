// Une séance : feuille d'émargement, ce que voit la salle, anomalies, corrections.

import { api } from '../api.js';
import {
  STATUTS, afficher, barre, dateLongue, echapper, etatSeance, etiquetteSource, heure, heureBadge,
  legendeBarre, nomEtudiant, ppm, puce, tuile,
} from '../ui.js';

const CHANGEMENTS = [['présent', 'Présent'], ['retard', 'Retard'], ['absent', 'Absent'], ['justifié', 'Justifier…']];

// Fenêtre de confirmation avec le motif (obligatoire pour une absence justifiée)
function demanderMotif(etudiant, avant, apres) {
  const dialogue = document.getElementById('dialogue-statut');
  const motif = document.getElementById('dialogue-motif');
  const obligatoire = apres === 'justifié';
  document.getElementById('dialogue-titre').textContent = obligatoire ? 'Justifier une absence' : 'Modifier la présence';
  document.getElementById('dialogue-texte').innerHTML =
    `${echapper(etudiant)} : ${puce(avant)} <span aria-hidden="true">→</span><span class="sr"> devient </span> ${puce(apres)}`;
  document.getElementById('dialogue-obligatoire').textContent = obligatoire ? '(obligatoire)' : '(facultatif)';
  motif.value = '';
  motif.required = obligatoire;
  return new Promise(resolve => {
    const finir = valeur => {
      dialogue.close();
      resolve(valeur);
    };
    document.getElementById('formulaire-statut').onsubmit = e => {
      e.preventDefault();
      if (obligatoire && !motif.value.trim()) { motif.focus(); return; }
      finir(motif.value.trim());
    };
    document.getElementById('dialogue-annuler').onclick = () => finir(null);
    dialogue.oncancel = e => { e.preventDefault(); finir(null); };   // touche Échap
    dialogue.showModal();
    motif.focus();
  });
}

function ligne(p, peutCorriger) {
  const boutons = CHANGEMENTS.filter(([statut]) => statut !== p.statut)
    .map(([statut, libelle]) => `<button type="button" class="bouton petit" data-etudiant="${echapper(p.etudiant)}"
      data-avant="${echapper(p.statut)}" data-statut="${statut}">${libelle}</button>`).join('');
  return `<tr>
    <td><a href="#/etudiant/${encodeURIComponent(p.etudiant)}">${nomEtudiant(p.etudiant, p.nom)}</a></td>
    <td>${puce(p.statut)}${p.corrige ? ' <span class="sous" title="statut corrigé à la main">✎ corrigé</span>' : ''}</td>
    <td>${heureBadge(p.badge)}</td>
    ${peutCorriger ? `<td class="pas-impression"><div class="actions">${boutons}</div></td>` : ''}
    <td class="col-impression signature"></td>
  </tr>`;
}

export async function vueSeance(zone, ctx) {
  const id = ctx.params[0];
  let s;
  try {
    s = await api(`/api/seance?id=${encodeURIComponent(id)}`);
  } catch (e) {
    if (e.code !== 400) throw e;
    ctx.titre('Séance');
    afficher(zone, `<a class="retour" href="#/seances">← Séances</a>
      <div class="carte"><h2>Cette séance n'a pas encore commencé</h2>
      <p>L'émargement s'ouvre 15 minutes avant le début du cours, dès les premiers badges.</p></div>`);
    return;
  }
  ctx.titre(`${s.matiere} — ${s.groupes.join(' + ')}`);

  if (!zone.dataset.ecoute) {
    zone.dataset.ecoute = '1';
    zone.addEventListener('click', async e => {
      if (e.target.closest('[data-imprimer]')) { window.print(); return; }
      const b = e.target.closest('button[data-statut]');
      if (!b) return;
      const motif = await demanderMotif(b.dataset.etudiant, b.dataset.avant, b.dataset.statut);
      if (motif === null) return;
      let texte;
      let classe;
      try {
        await api('/api/seance/statut', { seance: id, etudiant: b.dataset.etudiant, statut: b.dataset.statut, motif });
        texte = `${b.dataset.etudiant} : ${STATUTS[b.dataset.statut].libelle.toLowerCase()}. Modification enregistrée.`;
        classe = 'message ok';
      } catch (err) {
        texte = err.message;
        classe = 'message erreur';
      }
      await ctx.redessiner();                 // la page est redessinée, puis on affiche le message
      const message = zone.querySelector('#message');
      if (message) { message.textContent = texte; message.className = classe; }
    });
  }

  const peutCorriger = s.peut_corriger;
  const presents = s.presents + s.retards;
  const tuiles = [
    tuile(`${presents} / ${s.inscrits}`, 'présents', s.retards ? `dont ${s.retards} en retard` : '', 'bon'),
    tuile(s.absents, `absent${s.absents > 1 ? 's' : ''}`, s.justifies ? `+ ${s.justifies} justifié${s.justifies > 1 ? 's' : ''}` : '', s.absents ? 'alerte' : ''),
    tuile(s.a_verifier, 'à vérifier', 'carte peut-être prêtée', s.a_verifier ? 'alerte' : ''),
    tuile(s.attendus, `attendu${s.attendus > 1 ? 's' : ''}`, s.etat === 'en cours' ? 'pas encore badgé' : ''),
  ];
  const maintenant = s.salle_maintenant;
  const salle = maintenant ? `<div class="carte">
      <h2 class="titre-section">Dans la salle maintenant</h2>
      <p><b>${maintenant.personnes}</b> personnes ${maintenant.source === 'porte' ? 'comptées à la porte' : 'estimées par le Wi-Fi (±2)'}</p>
      <p>CO₂ : ${ppm(maintenant.co2)}</p>
      ${maintenant.alertes.map(a => `<div class="alerte ${a.niveau}"><span class="i">!</span><div>${echapper(a.texte)}</div></div>`).join('')}
    </div>` : '';
  const anomalies = s.anomalies.length ? `<div class="carte">
      <h2 class="titre-section">Badges et passages qui ne collent pas</h2>
      ${s.anomalies.map(a => `<div class="alerte ${a.type === 'carte prêtée' ? 'detecte' : 'suspect'}"><span class="i">!</span>
        <div><div><b>${a.nombre} × ${echapper(a.type)}</b></div><div class="quoi">${echapper(a.detail || explication(a.type))}</div></div></div>`).join('')}
    </div>` : '';
  const corrections = s.corrections.length ? `<section class="section pas-impression">
      <h2 class="titre-section">Modifications <span class="sous">qui a changé quoi</span></h2>
      <div class="tableau-conteneur"><table class="liste"><thead><tr><th>Quand</th><th>Étudiant</th><th>Avant</th><th>Après</th><th>Motif</th><th>Par</th></tr></thead><tbody>
      ${s.corrections.map(c => `<tr><td>${heureBadge(c.t)}</td><td>${echapper(c.etudiant)}</td><td>${puce(c.avant)}</td><td>${puce(c.apres)}</td>
        <td>${echapper(c.motif || '—')}</td><td>${echapper(c.auteur)}</td></tr>`).join('')}
      </tbody></table></div></section>` : '';
  const exports = s.cles.map(cle => `<a class="bouton" href="/api/export?classe=${encodeURIComponent(cle)}&du=${s.date}&au=${s.date}">Exporter ${echapper(cle)} (CSV)</a>`).join('');

  afficher(zone, `
    <a class="retour" href="#/seances?date=${s.date}">← Séances du ${dateLongue(s.date)}</a>
    <div class="seulement-impression"><h2>Feuille d'émargement — IUT de Sarcelles</h2></div>
    <div class="fiche-entete">
      <div>
        <h2>${echapper(s.matiere)} ${etiquetteSource(s.reel)}</h2>
        <div class="infos">
          <span>${s.cles.map((cle, i) => `<a href="#/classe/${encodeURIComponent(cle)}">${echapper(s.groupes[i] || cle)}</a>`).join(' + ')}</span>
          <span>Salle <b>${echapper(s.salle)}</b></span>
          <span>${dateLongue(s.date)}, ${heure(s.debut)}–${heure(s.fin)}</span>
          <span>${echapper(s.enseignant)}</span>
        </div>
      </div>
      <div class="actions">${etatSeance(s.etat)} <button type="button" class="bouton" data-imprimer>Imprimer la feuille</button> ${exports}</div>
    </div>
    <p id="message" class="message" role="status"></p>
    <section class="section"><div class="grille tuiles">${tuiles.join('')}</div>${barre(s)}${legendeBarre()}</section>
    ${salle || anomalies ? `<section class="section deux-colonnes">${salle}${anomalies}</section>` : ''}
    <section class="section">
      <h2 class="titre-section">Émargement <span class="sous">${s.etat === 'en cours' ? 'en direct, mis à jour toutes les 5 s' : 'séance close'}</span></h2>
      <div class="tableau-conteneur"><table class="liste">
        <thead><tr><th>Étudiant</th><th>Statut</th><th>Badge</th>${peutCorriger ? '<th class="pas-impression">Modifier</th>' : ''}<th class="col-impression signature">Signature</th></tr></thead>
        <tbody>${s.presences.map(p => ligne(p, peutCorriger)).join('')}</tbody>
      </table></div>
    </section>
    ${corrections}
    <p class="seulement-impression sous">Feuille produite par CampusTwin à partir des badges de la carte étudiante, vérifiés par le comptage de la porte.</p>`);
}
vueSeance.rafraichir = 5000;

function explication(type) {
  return {
    'entrée sans badge': 'Quelqu\'un est entré sans badger (oubli), ou la porte a compté un passage de trop.',
    'badge sans passage': 'Un badge sans passage compté : la porte a sans doute raté quelqu\'un.',
    'carte prêtée': 'Deux cartes badgées en moins de 3 s pour un seul passage.',
  }[type] || '';
}
