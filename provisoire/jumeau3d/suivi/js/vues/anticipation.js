// Jumeau prédictif : ce qui va se passer dans les 2 prochaines heures, ce que le jumeau décide pour la
// ventilation, et les changements de salle qu'il propose.

import { api } from '../api.js';
import { afficher, echapper, heure, pourcent, tuile } from '../ui.js';

const VITESSES = { arret: 'Arrêt', petite: 'Petite vitesse', grande: 'Grande vitesse' };

// ---------- courbes (SVG) ----------

function echelles(h0, h1, cMax, largeur, hauteur, marge) {
  const yMax = Math.max(1400, Math.ceil((cMax + 150) / 200) * 200);
  return {
    x: h => marge.g + ((h - h0) / (h1 - h0)) * (largeur - marge.g - marge.d),
    y: c => marge.h + (1 - (Math.min(c, yMax) - 400) / (yMax - 400)) * (hauteur - marge.h - marge.b),
    yMax,
  };
}

function chemin(points, x, y) {
  return points.map((p, i) => `${i ? 'L' : 'M'}${x(p.heure).toFixed(1)},${y(p.co2).toFixed(1)}`).join('');
}

// Grande courbe de la salle de l'automate : mesuré (trait plein), prévu (pointillés), plan de ventilation
function grandeCourbe(passe, prevu, plan, maintenant) {
  const L = 760;
  const H = 250;
  const marge = { g: 44, d: 12, h: 12, b: 58 };
  const h0 = Math.max(passe.length ? passe[0].heure : maintenant - 2, maintenant - 4);
  const h1 = maintenant + 2;
  const vus = passe.filter(p => p.heure >= h0);
  const cMax = Math.max(...vus.map(p => p.co2), ...prevu.map(p => p.co2), 0);
  const { x, y, yMax } = echelles(h0, h1, cMax, L, H, marge);
  const graduations = [];
  for (let c = 400; c <= yMax; c += 200) {
    graduations.push(`<line x1="${marge.g}" x2="${L - marge.d}" y1="${y(c)}" y2="${y(c)}" class="grille-svg"/>
      <text x="${marge.g - 6}" y="${y(c) + 4}" class="axe-svg" text-anchor="end">${c}</text>`);
  }
  const heures = [];
  for (let h = Math.ceil(h0); h <= h1; h++) {
    heures.push(`<text x="${x(h)}" y="${H - marge.b + 16}" class="axe-svg" text-anchor="middle">${h}h</text>`);
  }
  const seuils = [[800, 'seuil-svg'], [1200, 'seuil-svg fort']].map(([c, cl]) =>
    `<line x1="${marge.g}" x2="${L - marge.d}" y1="${y(c)}" y2="${y(c)}" class="${cl}"/>
     <text x="${L - marge.d - 4}" y="${y(c) - 4}" class="axe-svg" text-anchor="end">${c} ppm</text>`).join('');
  const bandeY = H - marge.b + 26;
  const bande = plan.map(s => `<rect x="${x(Math.max(s.debut, h0))}" y="${bandeY}" width="${Math.max(1, x(Math.min(s.fin, h1)) - x(Math.max(s.debut, h0)) - 2)}"
      height="14" rx="3" class="vitesse-${s.niveau}"><title>${heure(s.debut)}–${heure(s.fin)} : ${VITESSES[s.niveau]}</title></rect>`).join('');
  const donnees = JSON.stringify([...vus.map(p => ({ h: p.heure, c: p.co2, t: 'mesuré' })), ...prevu.map(p => ({ h: p.heure, c: p.co2, t: 'prévu' }))]);
  return `<svg class="courbe-co2" viewBox="0 0 ${L} ${H}" role="img" aria-label="CO2 mesuré et prévu, et vitesse de ventilation prévue"
      data-points='${echapper(donnees)}' data-h0="${h0}" data-h1="${h1}" data-marge="${marge.g},${marge.d}" data-largeur="${L}">
    ${graduations.join('')}${seuils}${heures.join('')}
    <line x1="${x(maintenant)}" x2="${x(maintenant)}" y1="${marge.h}" y2="${H - marge.b}" class="maintenant-svg"/>
    <text x="${x(maintenant) + 4}" y="${marge.h + 10}" class="axe-svg">maintenant</text>
    <path d="${chemin(vus, x, y)}" class="ligne-mesure"/>
    <path d="${chemin(prevu, x, y)}" class="ligne-prevue"/>
    <text x="${marge.g}" y="${bandeY + 11}" class="axe-svg" text-anchor="end" dx="-6">ventil.</text>
    ${bande}
    <line class="curseur-svg" y1="${marge.h}" y2="${H - marge.b}" x1="-10" x2="-10"/>
  </svg>`;
}

// Petite courbe d'une salle : les 2 prochaines heures
function petiteCourbe(serie) {
  const L = 170;
  const H = 40;
  const h0 = serie[0].heure;
  const h1 = serie[serie.length - 1].heure;
  const cMax = Math.max(...serie.map(p => p.co2));
  const { x, y } = echelles(h0, h1, cMax, L, H, { g: 2, d: 2, h: 3, b: 3 });
  const seuil = y(1200);
  return `<svg viewBox="0 0 ${L} ${H}" class="petite-courbe" aria-hidden="true">
    ${seuil > 3 ? `<line x1="2" x2="${L - 2}" y1="${seuil}" y2="${seuil}" class="seuil-svg fort"/>` : ''}
    <path d="${chemin(serie, x, y)}" class="ligne-prevue pleine"/></svg>`;
}

function classePpm(c) {
  return c >= 1200 ? 'ppm-mauvais' : c >= 800 ? 'ppm-moyen' : 'ppm-bon';
}

// ---------- places des salles : frise de la journée ----------

// Remplissage (étudiants / places) en 4 niveaux d'un même bleu, et le rouge quand il y a plus d'étudiants que de places
const REMPLISSAGE = [
  { classe: 'remplissage-trop', encre: 'encre-claire', texte: 'plus d\'étudiants que de places', min: 1.0001 },
  { classe: 'remplissage-4', encre: 'encre-claire', texte: 'plus de 90 %', min: 0.9001 },
  { classe: 'remplissage-3', encre: 'encre-claire', texte: '70 à 90 %', min: 0.7 },
  { classe: 'remplissage-2', encre: 'encre-foncee', texte: '40 à 70 %', min: 0.4 },
  { classe: 'remplissage-1', encre: 'encre-foncee', texte: 'moins de 40 %', min: 0 },
];
const ETATS = { trop_petite: 'salle trop petite', pleine: 'salle pleine', adaptee: 'salle adaptée', trop_grande: 'salle trop grande' };
const SOURCES = { porte: 'comptés à la porte', badges: 'badgés', 'prévu': 'prévus' };

const niveauRemplissage = r => REMPLISSAGE.find(n => r >= n.min);

function frise(cap) {
  const L = 760;
  const marge = { g: 112, d: 8, h: 22 };              // assez pour « SAR Amphi 1 · 120 »
  const ligne = 28;
  const epaisseur = 22;
  const [h0, h1] = [8, 19];
  const H = marge.h + cap.salles.length * ligne + 2;
  const x = h => marge.g + ((Math.min(Math.max(h, h0), h1) - h0) / (h1 - h0)) * (L - marge.g - marge.d);
  const heures = [];
  for (let h = h0; h <= h1; h++) {
    heures.push(`<line x1="${x(h)}" x2="${x(h)}" y1="${marge.h - 4}" y2="${H}" class="grille-svg"/>
      <text x="${x(h)}" y="${marge.h - 9}" class="axe-svg" text-anchor="middle">${h}h</text>`);
  }
  const lignes = cap.salles.map((s, i) => {
    const y = marge.h + i * ligne + (ligne - epaisseur) / 2;
    const blocs = s.cours.map(c => {
      const x0 = x(c.debut) + 1;                       // 2 px de vide entre deux cours qui se suivent
      const w = Math.max(2, x(c.fin) - 1 - x0);
      const n = niveauRemplissage(c.etudiants / s.places);
      const texte = `${c.source === 'prévu' ? '~' : ''}${c.etudiants}/${s.places}`;
      const info = {
        titre: `${c.matiere}, ${c.groupes.join(' + ')}`,
        valeur: `${c.etudiants} étudiants pour ${s.places} places (${Math.round(c.remplissage * 100)} %)`,
        detail: `${s.salle}, ${heure(c.debut)}–${heure(c.fin)}, ${SOURCES[c.source]}, ${ETATS[c.etat]}`
          + (c.plus_petite ? `. ${c.plus_petite.salle} (${c.plus_petite.places} places) était libre` : ''),
      };
      const etiquette = texte.length * 6.8 + 8 <= w
        ? `<text x="${x0 + w / 2}" y="${y + epaisseur / 2 + 4}" class="texte-bloc ${n.encre}" text-anchor="middle">${texte}</text>` : '';
      return `<g class="bloc" tabindex="0" role="img" aria-label="${echapper(`${info.titre}, ${info.valeur}, ${info.detail}`)}"
          data-info="${echapper(JSON.stringify(info))}"><rect x="${x0}" y="${y}" width="${w}" height="${epaisseur}" class="${n.classe}"/>${etiquette}</g>`;
    }).join('');
    return `<text x="${marge.g - 8}" y="${y + epaisseur / 2 + 4}" class="axe-svg" text-anchor="end">${echapper(s.salle)} (${s.places})</text>${blocs}`;
  }).join('');
  const maintenant = cap.heure > h0 && cap.heure < h1
    ? `<line x1="${x(cap.heure)}" x2="${x(cap.heure)}" y1="${marge.h - 4}" y2="${H}" class="maintenant-svg"/>` : '';
  return `<svg class="frise-salles" viewBox="0 0 ${L} ${H}" role="group" aria-label="Remplissage des salles heure par heure">
    ${heures.join('')}${lignes}${maintenant}</svg>`;
}

function tableauCapacite(cap) {
  const lignes = cap.salles.flatMap(s => s.cours.map(c => `<tr>
      <td class="nowrap"><b>${echapper(s.salle)}</b></td><td class="nowrap">${heure(c.debut)}–${heure(c.fin)}</td>
      <td>${echapper(c.matiere)} <span class="sous">${echapper(c.groupes.join(' + '))}</span></td>
      <td class="nombre">${c.etudiants} / ${s.places}</td><td class="nombre">${Math.round(c.remplissage * 100)} %</td>
      <td class="sous">${SOURCES[c.source]}</td><td>${ETATS[c.etat]}${c.plus_petite ? ` <span class="sous">(${echapper(c.plus_petite.salle)} libre)</span>` : ''}</td>
    </tr>`)).join('');
  return `<details class="vue-tableau"><summary>Voir en tableau</summary><div class="tableau-conteneur"><table class="liste">
    <thead><tr><th>Salle</th><th>Heure</th><th>Cours</th><th class="nombre">Étudiants / places</th><th class="nombre">Remplissage</th><th>Nombre</th><th>Salle</th></tr></thead>
    <tbody>${lignes}</tbody></table></div></details>`;
}

// ---------- chauffage et éclairage selon l'occupation ----------

const CHAUFFAGES = { confort: 'Confort', reduit: 'Réduit', hors_gel: 'Hors-gel' };

function sectionAmbiance(a) {
  const b = a.bilan;
  const auto = a.automate.connecte ? 'automate connecté' : 'automate non connecté';
  const economie = e => (e && e.economie != null ? `−${pourcent(e.economie)}` : '—');
  const tuiles = [
    tuile(CHAUFFAGES[a.chauffage], `chauffage ${echapper(a.salle)}`, `lumière ${a.eclairage ? 'allumée' : 'éteinte'}, ${auto}`),
    tuile(economie(b && b.salle), `énergie ${echapper(a.salle)} aujourd'hui`,
      b ? `${b.salle.jumeau} kWh au lieu de ${b.salle.fixe} kWh` : '', 'bon'),
    tuile(economie(b && b.batiment), 'estimation pour les 23 salles',
      b ? `${b.batiment.jumeau} kWh au lieu de ${b.batiment.fixe} kWh` : '', 'bon'),
  ];
  return `<section class="section">
      <h2 class="titre-section">Chauffage et éclairage</h2>
      <div class="grille tuiles">${tuiles.join('')}</div>
      <p class="sous">Confort pendant les cours et 45 min avant, réduit le reste de la journée, hors-gel la nuit.
        Lumière seulement quand il y a quelqu'un. Comparé à l'horaire fixe (confort de 7 h à 19 h).</p>
    </section>`;
}

function sectionCapacite(cap) {
  const ch = cap.chiffres;
  const a = cap.appris;
  const tuiles = [
    tuile(pourcent(ch.remplissage_moyen), 'remplissage moyen', 'étudiants / places'),
    tuile(pourcent(ch.occupation), 'occupation des salles', 'créneaux 8h–18h'),
    tuile(ch.trop_petite, `salle${ch.trop_petite > 1 ? 's' : ''} trop petite${ch.trop_petite > 1 ? 's' : ''}`, `${ch.pleine} pleine${ch.pleine > 1 ? 's' : ''} (plus de 90 %)`,
      ch.trop_petite ? 'alerte' : ''),
    tuile(ch.trop_grande, `salle${ch.trop_grande > 1 ? 's' : ''} trop grande${ch.trop_grande > 1 ? 's' : ''}`, 'moins de 40 %'),
  ];
  const grandes = cap.salles.flatMap(s => s.cours.filter(c => c.etat === 'trop_grande' && c.moment === 'à venir').map(c =>
    `<li>${echapper(c.matiere)} (${echapper(c.groupes.join(' + '))}, ${heure(c.debut)}) :
      ${c.etudiants} étudiants pour ${s.places} places en ${echapper(s.salle)}${c.plus_petite
        ? `, ${echapper(c.plus_petite.salle)} (${c.plus_petite.places} places) est libre` : ''}</li>`));
  const effet = d => (Math.abs(d) < 0.01 ? 'normal' : `${d > 0 ? '+' : '−'}${Math.round(Math.abs(d) * 100)} %`);
  const moins = a.groupes.slice().sort((g, h) => g.taux - h.taux).slice(0, 3)
    .map(g => `${echapper(g.nom)} (${pourcent(g.taux)})`).join(', ');
  return `<section class="section">
      <h2 class="titre-section">Places des salles aujourd'hui</h2>
      <div class="grille tuiles">${tuiles.join('')}</div>
      <div class="carte">
        <div class="conteneur-courbe">${frise(cap)}<div id="bulle-capacite" class="bulle bulle-bloc" hidden></div></div>
        <div class="legende">${REMPLISSAGE.slice().reverse().map(n => `<span><i class="${n.classe}"></i>${n.texte}</span>`).join('')}
          <span>~ : nombre prévu</span></div>
        <p class="sous">Présence moyenne sur 14 jours : ${pourcent(a.moyen)} (ce jour : matin ${effet(a.demi_journees.matin)},
          après-midi ${effet(a.demi_journees['après-midi'])}).${moins ? ` Groupes qui viennent le moins : ${moins}.` : ''}</p>
        ${tableauCapacite(cap)}
      </div>
      ${grandes.length ? `<div class="carte"><b>Salles trop grandes à venir</b><ul class="liste-simple">${grandes.join('')}</ul></div>` : ''}
    </section>`;
}

// ---------- page ----------

export async function vueAnticipation(zone, ctx) {
  const [d, passe] = await Promise.all([api('/api/previsions'), api(`/api/historique?salle=${encodeURIComponent('SAR 200')}`)]);
  ctx.titre('Anticipation');
  const cmd = d.commande;
  const b = cmd.bilan;
  const auto = d.salles.find(s => s.salle === cmd.salle);

  if (!zone.dataset.ecoute) {
    zone.dataset.ecoute = '1';
    zone.addEventListener('click', async e => {
      const bouton = e.target.closest('[data-action]');
      if (!bouton) return;
      bouton.disabled = true;
      try {
        if (bouton.dataset.action === 'strategie') {
          await api('/api/commande', { strategie: bouton.dataset.valeur });
        } else {
          const echange = bouton.dataset.echangeCours ? { cours: bouton.dataset.echangeCours, salle: bouton.dataset.echangeSalle } : null;
          await api('/api/proposition', { action: bouton.dataset.action, cours: bouton.dataset.cours, salle: bouton.dataset.salle, echange });
        }
      } finally {
        await ctx.redessiner();
      }
    });
    // Curseur sur la grande courbe : la valeur sous la souris
    zone.addEventListener('mousemove', e => {
      const svg = e.target.closest('svg.courbe-co2');
      const bulle = zone.querySelector('#bulle');
      if (!svg || !bulle) return;
      const r = svg.getBoundingClientRect();
      const [mg, md] = svg.dataset.marge.split(',').map(Number);
      const L = Number(svg.dataset.largeur);
      const xs = (e.clientX - r.left) * (L / r.width);
      const h0 = Number(svg.dataset.h0);
      const h1 = Number(svg.dataset.h1);
      const h = h0 + ((xs - mg) / (L - mg - md)) * (h1 - h0);
      const points = JSON.parse(svg.dataset.points);
      const p = points.reduce((a, q) => (Math.abs(q.h - h) < Math.abs(a.h - h) ? q : a), points[0]);
      if (!p) return;
      const curseur = svg.querySelector('.curseur-svg');
      const xp = mg + ((p.h - h0) / (h1 - h0)) * (L - mg - md);
      curseur.setAttribute('x1', xp);
      curseur.setAttribute('x2', xp);
      bulle.hidden = false;
      bulle.textContent = `${heure(p.h)} · ${Math.round(p.c)} ppm (${p.t})`;
      bulle.style.left = `${(xp / L) * r.width}px`;
    });
    zone.addEventListener('mouseleave', () => { const bulle = zone.querySelector('#bulle'); if (bulle) bulle.hidden = true; }, true);
    // Frise des salles : le détail d'un cours au survol ou au clavier
    const montrerBloc = bloc => {
      const bulle = zone.querySelector('#bulle-capacite');
      if (!bulle) return;
      if (!bloc) { bulle.hidden = true; return; }
      const info = JSON.parse(bloc.dataset.info);
      const svg = bloc.ownerSVGElement;
      const r = svg.getBoundingClientRect();
      const b = bloc.getBoundingClientRect();
      bulle.replaceChildren(...[['b', info.valeur], ['span', info.titre], ['span', info.detail]].map(([balise, texte]) => {
        const e = document.createElement(balise);
        e.textContent = texte;                                         // textes venus des données : jamais en HTML
        return e;
      }));
      bulle.hidden = false;
      bulle.style.left = `${Math.min(Math.max(b.left - r.left + b.width / 2, 120), r.width - 120)}px`;
      bulle.style.top = `${b.bottom - r.top + 6}px`;
    };
    zone.addEventListener('pointerover', e => montrerBloc(e.target.closest('.bloc')));
    zone.addEventListener('focusin', e => montrerBloc(e.target.closest('.bloc')));
    zone.addEventListener('focusout', () => montrerBloc(null));
  }

  const tuiles = [
    tuile(b && b.economie != null ? `−${pourcent(b.economie)}` : '—', 'énergie de ventilation', b ? `${b.energie_kwh.jumeau} kWh au lieu de ${b.energie_kwh.regle} kWh` : '', 'bon'),
    tuile(b ? `${b.minutes_au_dessus_1000.jumeau} min` : '—', 'au-dessus de 1000 ppm', b ? `${b.minutes_au_dessus_1000.regle} min avec la règle simple` : ''),
    tuile(d.precision['30 min'].erreur_moyenne != null ? `± ${d.precision['30 min'].erreur_moyenne} ppm` : '—', 'erreur de prévision à 30 min',
      d.precision['60 min'].erreur_moyenne != null ? `± ${d.precision['60 min'].erreur_moyenne} ppm à 1 h` : ''),
    tuile(d.propositions.length, `proposition${d.propositions.length > 1 ? 's' : ''} de salle`, `${d.changements.length} acceptée${d.changements.length > 1 ? 's' : ''}`),
  ];

  const raisons = p => [
    p.motifs.includes('air') ? '<span class="raison">Air mauvais prévu</span>' : '',
    p.motifs.includes('trop_petite') ? '<span class="raison">Salle trop petite</span>' : '',
  ].filter(Boolean).join(', ');
  const salleDe = (titre, salle, places, etudiants, pic) => `<div><span class="sous">${titre}</span><b>${echapper(salle)}</b>
      <span class="${etudiants > places ? 'ppm-mauvais' : ''}">${etudiants} étudiants / ${places} places</span>
      ${pic != null ? `<span class="${classePpm(pic)}">${pic} ppm prévus</span>` : ''}</div>`;
  const propositions = d.propositions.length ? d.propositions.map(p => `<div class="carte proposition">
      <div class="entete"><b>${echapper(p.matiere)}, ${heure(p.debut)}–${heure(p.fin)}</b> <span class="sous">${echapper(p.groupes.join(' + '))}, ${echapper(p.enseignant)}, ${p.etudiants} étudiants attendus sur ${p.inscrits}</span></div>
      <div class="raisons">${raisons(p)}</div>
      ${p.proposee ? `<div class="deplacement">
        ${salleDe('Salle prévue', p.salle, p.places, p.etudiants, p.pic)}
        <span class="fleche" aria-hidden="true">→</span>
        ${salleDe('Salle proposée', p.proposee, p.places_proposee, p.etudiants, p.pic_propose)}
      </div>` : `<p class="message erreur">${p.etudiants} étudiants pour ${p.places} places en ${echapper(p.salle)}. Pas de salle libre ni d'échange possible.</p>`}
      ${p.echange ? `<p class="echange">Échange : ${echapper(p.echange.matiere)} (${echapper(p.echange.groupes.join(' + '))},
        ${heure(p.echange.debut)}–${heure(p.echange.fin)}, ${p.echange.etudiants} étudiants) va de ${echapper(p.echange.salle)}
        à ${echapper(p.echange.vers)}, avec <span class="${classePpm(p.echange.pic_apres)}">${p.echange.pic_apres} ppm prévus</span>
        ${p.echange.pic_avant != null ? `au lieu de ${p.echange.pic_avant}` : ''}.</p>` : ''}
      <details class="negociation"><summary>Réponse des autres salles (${p.negociation.length})</summary>
        <ul>${p.negociation.map(r => `<li><b>${echapper(r.salle)}</b> : ${echapper(r.reponse)}${r.detail ? ` <span class="sous">(${echapper(r.detail)})</span>` : ''}</li>`).join('')}</ul>
      </details>
      <div class="actions">
        ${p.proposee ? `<button type="button" class="bouton principal-bouton" data-action="accepter" data-cours="${echapper(p.cours)}" data-salle="${echapper(p.proposee)}"
          ${p.echange ? `data-echange-cours="${echapper(p.echange.cours)}" data-echange-salle="${echapper(p.echange.vers)}"` : ''}>${p.echange ? 'Accepter l\'échange' : 'Accepter le changement'}</button>` : ''}
        <button type="button" class="bouton" data-action="ignorer" data-cours="${echapper(p.cours)}">Ignorer</button>
      </div>
    </div>`).join('') : '<p class="vide">Aucune proposition.</p>';
  const changements = d.changements.length ? `<ul class="liste-simple">${d.changements.map(c =>
    `<li>${echapper(c.cours)} : ${echapper(c.salle_avant)} → ${echapper(c.salle_apres)} (par ${echapper(c.auteur)})</li>`).join('')}</ul>` : '';

  const plan = cmd.plan.length ? cmd.plan : [];
  const prochain = plan.find(s => s.niveau !== cmd.niveau);
  const salles = d.salles.slice().sort((a, c) => (c.pic?.co2 || 0) - (a.pic?.co2 || 0)).map(s => `<tr>
      <td class="nowrap"><b>${echapper(s.salle)}</b></td>
      <td class="nombre"><span class="${classePpm(s.maintenant)}">${s.maintenant}</span></td>
      <td>${s.pic ? `<span class="${classePpm(s.pic.co2)}">${s.pic.co2} ppm</span> vers ${heure(s.pic.heure)}` : '—'}</td>
      <td>${s.au_dessus_1200 != null ? `<span class="ppm-mauvais">dès ${heure(s.au_dessus_1200)}</span>` : 'non'}</td>
      <td>${petiteCourbe(s.serie)}</td>
      <td class="sous">${{ appris: 'mesuré', automate: 'automate', 'a priori': 'supposé' }[s.source_debit]}</td>
    </tr>`).join('');

  afficher(zone, `
    <section class="section"><div class="grille tuiles">${tuiles.join('')}</div></section>
    <section class="section">
      <h2 class="titre-section">Changements de salle proposés</h2>
      <div class="grille propositions">${propositions}</div>${changements}
    </section>
    ${d.capacite ? sectionCapacite(d.capacite) : ''}
    ${d.ambiance ? sectionAmbiance(d.ambiance) : ''}
    <section class="section">
      <h2 class="titre-section">Ventilation de ${echapper(cmd.salle)}</h2>
      <div class="carte">
        <div class="barre-outils">
          <span>Maintenant : <b>${VITESSES[cmd.niveau] || '—'}</b>${prochain ? `, puis ${VITESSES[prochain.niveau].toLowerCase()} à ${heure(prochain.debut)}` : ''}</span>
          <span class="espace"></span>
          <span>Commande :</span>
          <button type="button" class="bouton petit ${cmd.strategie === 'predictive' ? 'principal-bouton' : ''}" data-action="strategie" data-valeur="predictive">Prédictive</button>
          <button type="button" class="bouton petit ${cmd.strategie === 'reactive' ? 'principal-bouton' : ''}" data-action="strategie" data-valeur="reactive">Règle simple</button>
        </div>
        <div class="conteneur-courbe">${grandeCourbe(passe.map(p => ({ heure: p.heure, co2: p.C })), auto ? auto.serie : [], plan, d.heure)}
          <div id="bulle" class="bulle" hidden></div></div>
        <div class="legende">
          <span><i class="trait-plein"></i>CO₂ mesuré</span><span><i class="trait-pointille"></i>CO₂ prévu</span>
          <span><i class="vitesse-arret"></i>Arrêt</span><span><i class="vitesse-petite"></i>Petite vitesse</span><span><i class="vitesse-grande"></i>Grande vitesse</span>
        </div>
        <p class="sous">Chaque minute, on simule les 90 minutes suivantes pour chaque vitesse et on garde la moins coûteuse (énergie + air).</p>
      </div>
    </section>
    <section class="section">
      <h2 class="titre-section">CO₂ prévu dans chaque salle (2 heures)</h2>
      <div class="tableau-conteneur"><table class="liste">
        <thead><tr><th>Salle</th><th class="nombre">CO₂ maintenant</th><th>Pic prévu</th><th>Au-dessus de 1200 ppm</th><th>2 prochaines heures</th><th>Débit</th></tr></thead>
        <tbody>${salles}</tbody>
      </table></div>
      <p class="sous">En simulation, la prévision est presque parfaite (même modèle des deux côtés). En vrai, l'erreur sera plus grande.</p>
    </section>`);
}
vueAnticipation.rafraichir = 10000;
