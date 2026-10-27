// Petits morceaux d'interface réutilisés par toutes les pages.

export function echapper(texte) {
  return String(texte ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---------- dates et heures ----------

const JOURS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];

export function heure(h) {
  const minutes = Math.round(h * 60);
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}h${String(minutes % 60).padStart(2, '0')}`;
}

export function dateDe(iso) {
  const [a, m, j] = iso.split('-').map(Number);
  return new Date(a, m - 1, j);
}

export function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function dateLongue(texte) {
  const d = dateDe(texte);
  return `${JOURS[d.getDay()]} ${d.getDate()} ${MOIS[d.getMonth()]}`;
}

export function dateCourte(texte) {
  const d = dateDe(texte);
  return `${JOURS[d.getDay()].slice(0, 3)}. ${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export function ajouterJours(texte, n) {
  const d = dateDe(texte);
  d.setDate(d.getDate() + n);
  return iso(d);
}

export function lundiDe(texte) {
  const d = dateDe(texte);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return iso(d);
}

export function heureBadge(t) {
  if (t == null) return '-';
  const d = new Date(t * 1000);
  return `${String(d.getHours()).padStart(2, '0')}h${String(d.getMinutes()).padStart(2, '0')}`;
}

export function pourcent(x) {
  return x == null ? '-' : `${Math.round(x * 100)} %`;
}

// ---------- statuts ----------

export const STATUTS = {
  'présent': { libelle: 'Présent', court: 'P', classe: 'present' },
  retard: { libelle: 'En retard', court: 'R', classe: 'retard' },
  absent: { libelle: 'Absent', court: 'A', classe: 'absent' },
  'justifié': { libelle: 'Justifié', court: 'J', classe: 'justifie' },
  'à vérifier': { libelle: 'À vérifier', court: '?', classe: 'verifier' },
  attendu: { libelle: 'Attendu', court: '-', classe: 'attendu' },
};

export function puce(statut) {
  const s = STATUTS[statut] || { libelle: statut, classe: 'attendu' };
  return `<span class="statut s-${s.classe}">${s.libelle}</span>`;
}

export function caseStatut(statut, corrige, titre, lien) {
  const s = STATUTS[statut] || STATUTS.attendu;
  const contenu = `<span class="case-statut s-${s.classe}${corrige ? ' corrige' : ''}" title="${echapper(titre)}"
    aria-label="${echapper(titre)}">${s.court}</span>`;
  return lien ? `<a href="${lien}" class="lien-case">${contenu}</a>` : contenu;
}

// Barre d'émargement : une part par statut, dans l'ordre de lecture
const ORDRE = [['presents', 'present'], ['retards', 'retard'], ['a_verifier', 'verifier'], ['justifies', 'justifie'],
  ['absents', 'absent'], ['attendus', 'attendu']];

export function barre(c) {
  const total = ORDRE.reduce((n, [cle]) => n + (c[cle] || 0), 0);
  if (!total) return '<div class="barre" aria-hidden="true"></div>';
  const titre = `${c.presents || 0} présents, ${c.retards || 0} en retard, ${c.absents || 0} absents, ${c.justifies || 0} justifiés, ${c.a_verifier || 0} à vérifier, ${c.attendus || 0} attendus`;
  return `<div class="barre" role="img" aria-label="${titre}" title="${titre}">${ORDRE.map(([cle, classe]) =>
    (c[cle] ? `<span class="b-${classe}" style="flex:${c[cle]}"></span>` : '')).join('')}</div>`;
}

export function legendeBarre() {
  const items = [['present', 'Présent'], ['retard', 'Retard'], ['verifier', 'À vérifier'], ['justifie', 'Justifié'],
    ['absent', 'Absent'], ['attendu', 'Attendu']];
  return `<div class="legende">${items.map(([c, t]) => `<span><i class="b-${c}" style="background:var(--${c}-plein)"></i>${t}</span>`).join('')}</div>`;
}

export function etatSeance(etat) {
  const classe = { 'en cours': 'en-cours', 'terminée': 'terminee', 'à venir': 'a-venir' }[etat] || 'a-venir';
  return `<span class="etat-seance etat-${classe}">${echapper(etat)}</span>`;
}

export function etiquetteSource(reel) {
  return reel ? '<span class="etiquette-reel">(EDT réel)</span>' : '<span class="etiquette-simule">(simulé)</span>';
}

export function ppm(co2) {
  if (co2 == null) return '-';
  const classe = co2 >= 1200 ? 'mauvais' : co2 >= 800 ? 'moyen' : 'bon';
  const texte = { bon: 'bon', moyen: 'moyen', mauvais: 'mauvais' }[classe];
  return `<span class="ppm-${classe}">${Math.round(co2)} ppm (${texte})</span>`;
}

export function tuile(valeur, libelle, detail = '', ton = '') {
  return `<div class="tuile${ton ? ` ton-${ton}` : ''}"><span class="valeur">${valeur}</span> ${libelle}${detail ? ` <span class="sous">(${detail})</span>` : ''}</div>`;
}

export function nomEtudiant(id, nom) {
  return nom ? `${echapper(nom)} <span class="sous">${echapper(id)}</span>` : echapper(id);
}

export function inscritsTexte(c) {
  const presents = (c.presents || 0) + (c.retards || 0);
  return `${presents} / ${c.inscrits || 0}`;
}

// Remplace le contenu seulement s'il a changé (pas de clignotement aux rafraîchissements)
export function afficher(zone, html) {
  if (zone.dataset.html !== html) {
    zone.innerHTML = html;
    zone.dataset.html = html;
  }
}

// ---------- période affichée (une semaine par défaut) ----------

export function periodeDe(ctx) {
  const du = ctx.query.get('du');
  const au = ctx.query.get('au');
  if (du && au) return { du, au };
  const lundi = lundiDe(ctx.info()?.date || iso(new Date()));
  return { du: lundi, au: ajouterJours(lundi, 6) };
}

export function navigationPeriode(base, { du, au }, autres = '') {
  const avant = `${base}${base.includes('?') ? '&' : '?'}du=${ajouterJours(du, -7)}&au=${ajouterJours(au, -7)}${autres}`;
  const apres = `${base}${base.includes('?') ? '&' : '?'}du=${ajouterJours(du, 7)}&au=${ajouterJours(au, 7)}${autres}`;
  return `<a class="bouton" href="${avant}" aria-label="Semaine précédente">◀</a>
    <span class="periode">du ${dateCourte(du)} au ${dateCourte(au)}</span>
    <a class="bouton" href="${apres}" aria-label="Semaine suivante">▶</a>
    <a class="bouton discret" href="${base}${autres ? `${base.includes('?') ? '&' : '?'}${autres.slice(1)}` : ''}">Cette semaine</a>`;
}

export function barreTaux(taux) {
  if (taux == null) return '<span class="sous">-</span>';
  return `<div class="cellule-barre"><div class="barre" aria-hidden="true"><span class="b-present" style="flex:${taux}"></span>
    <span class="b-attendu" style="flex:${1 - taux}"></span></div><b>${pourcent(taux)}</b></div>`;
}
