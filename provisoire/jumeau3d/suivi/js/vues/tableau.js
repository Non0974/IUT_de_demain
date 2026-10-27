// Tableau de bord : ce qui se passe maintenant dans l'IUT (ou dans les cours de l'enseignant).

import { api } from '../api.js';
import { afficher, barre, echapper, etatSeance, etiquetteSource, heure, inscritsTexte, legendeBarre, pourcent, ppm, tuile } from '../ui.js';

function carteSeance(s) {
  const source = s.source === 'porte' ? 'comptées à la porte' : 'estimées par le Wi-Fi';
  return `<a class="carte carte-seance" href="#/seance/${encodeURIComponent(s.id)}">
    <div class="entete"><span class="salle">${echapper(s.salle)}</span>${etatSeance('en cours')}</div>
    <div><span class="matiere">${echapper(s.matiere)}</span> ${etiquetteSource(s.reel)}</div>
    <div class="sous">${echapper(s.groupes.join(' + '))} · ${echapper(s.enseignant)} · ${heure(s.debut)}–${heure(s.fin)}</div>
    ${barre(s)}
    <div class="chiffres"><span><b>${inscritsTexte(s)}</b> présents</span><span>${s.absents} absent${s.absents > 1 ? 's' : ''} · ${s.attendus} attendu${s.attendus > 1 ? 's' : ''}${s.a_verifier ? ` · ${s.a_verifier} à vérifier` : ''}</span></div>
    <div class="air">${s.personnes} personnes (${source}), CO₂ ${ppm(s.co2)}</div>
  </a>`;
}

function alerte(a) {
  const lien = a.seance ? `#/seance/${encodeURIComponent(a.seance)}` : a.etudiant ? `#/etudiant/${encodeURIComponent(a.etudiant)}`
    : a.ticket ? '#/tickets' : '#/';
  const quoi = a.salle ? `Salle ${echapper(a.salle)}` : a.etudiant ? `Étudiant ${echapper(a.nom || a.etudiant)}` : '';
  return `<a class="alerte ${a.niveau}" href="${lien}"><div>${echapper(a.texte)}</div><div class="quoi">${quoi}</div></a>`;
}

export async function vueTableau(zone, ctx) {
  const d = await api('/api/tableau');
  const enseignant = ctx.utilisateur.role === 'enseignant';
  ctx.titre(enseignant ? 'Mes cours aujourd\'hui' : 'Tableau de bord');
  const c = d.chiffres;
  const tuiles = [
    tuile(c.seances_en_cours, 'séances en cours', `${c.seances_terminees} terminées sur ${c.seances_du_jour}`),
    tuile(c.presents_maintenant, 'présents', c.attendus_maintenant ? `${c.attendus_maintenant} pas encore arrivés` : '', 'bon'),
    tuile(c.absents_maintenant, `absent${c.absents_maintenant > 1 ? 's' : ''}`, '', c.absents_maintenant ? 'alerte' : ''),
    tuile(pourcent(c.taux_jour), 'présence du jour'),
    tuile(c.alertes, `alerte${c.alertes > 1 ? 's' : ''}`, '', c.alertes ? 'alerte' : ''),
  ];
  const enCours = d.en_cours.length
    ? `<div class="grille cartes">${d.en_cours.map(carteSeance).join('')}</div>${legendeBarre()}`
    : '<p class="vide">Aucune séance en cours.</p>';
  const aVenir = d.a_venir.length
    ? `<div class="tableau-conteneur"><table class="liste"><thead><tr><th>Horaire</th><th>Salle</th><th>Cours</th><th>Classe</th></tr></thead><tbody>
      ${d.a_venir.map(s => `<tr><td class="nowrap">${heure(s.debut)}–${heure(s.fin)}</td><td class="nowrap">${echapper(s.salle)}</td>
        <td>${echapper(s.matiere)}<div class="sous">${echapper(s.enseignant)}</div></td><td>${echapper(s.groupes.join(' + '))}</td></tr>`).join('')}
      </tbody></table></div>`
    : '<p class="vide">Plus de séance prévue aujourd\'hui.</p>';
  const alertes = d.alertes.length ? `<div class="alertes">${d.alertes.map(alerte).join('')}</div>` : '<p class="vide">Aucune alerte.</p>';

  afficher(zone, `
    <section class="section"><div class="grille tuiles">${tuiles.join('')}</div></section>
    <section class="section">
      <h2 class="titre-section">En ce moment</h2>
      ${enCours}
    </section>
    <div class="deux-colonnes">
      <section class="section"><h2 class="titre-section">À venir aujourd'hui</h2>${aVenir}</section>
      <section class="section"><h2 class="titre-section">Alertes</h2>${alertes}</section>
    </div>`);
}
vueTableau.rafraichir = 5000;
