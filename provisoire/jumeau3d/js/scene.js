// Scène 3D de la salle : murs, tables, porte avec ses capteurs et le lecteur de badge,
// fenêtre, ventilation, étudiants qui entrent et sortent, couleur de l'air selon le CO2, flux d'air.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { SALLE } from './simulation.js';

const L = SALLE.longueur;   // axe x
const W = SALLE.largeur;    // axe z
const H = SALLE.hauteur;    // axe y
const PORTE = { x: L / 2, z: 2.3 };
const COULEURS_ETUDIANTS = [0x3b6ea5, 0xc0504d, 0x6aa84f, 0xe69138, 0x8e7cc3, 0x45818e, 0xbf9000, 0x3d85c6];

function couleurCO2(ppm) {
  // vert (420) -> jaune (800) -> orange (1200) -> rouge (2000)
  const pts = [[420, 0x3cb371], [800, 0xf4d03f], [1200, 0xe67e22], [2000, 0xc0392b]];
  if (ppm <= pts[0][0]) return new THREE.Color(pts[0][1]);
  for (let i = 1; i < pts.length; i++) {
    if (ppm <= pts[i][0]) {
      const a = (ppm - pts[i - 1][0]) / (pts[i][0] - pts[i - 1][0]);
      return new THREE.Color(pts[i - 1][1]).lerp(new THREE.Color(pts[i][1]), a);
    }
  }
  return new THREE.Color(pts[pts.length - 1][1]);
}

function boite(lx, ly, lz, couleur, options = {}) {
  const m = new THREE.Mesh(
    new THREE.BoxGeometry(lx, ly, lz),
    new THREE.MeshStandardMaterial({ color: couleur, roughness: 0.8, ...options }),
  );
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

function etiquette(texte, classe = 'etiquette') {
  const div = document.createElement('div');
  div.className = classe;
  div.textContent = texte;
  return new CSS2DObject(div);
}

export function creerScene(conteneur) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  conteneur.appendChild(renderer.domElement);

  const rendererLabels = new CSS2DRenderer();
  rendererLabels.domElement.className = 'calque-etiquettes';
  conteneur.appendChild(rendererLabels.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe9edf2);

  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(9, 9, 11);
  const controles = new OrbitControls(camera, rendererLabels.domElement);
  controles.target.set(0, 0.8, 0);
  controles.maxPolarAngle = Math.PI / 2.05;
  controles.enableDamping = true;

  scene.add(new THREE.HemisphereLight(0xffffff, 0xb0b0b0, 1.6));
  const soleil = new THREE.DirectionalLight(0xffffff, 1.4);
  soleil.position.set(6, 12, 8);
  soleil.castShadow = true;
  soleil.shadow.mapSize.set(2048, 2048);
  Object.assign(soleil.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8 });
  scene.add(soleil);

  // --- Sol et murs ---
  const sol = new THREE.Mesh(new THREE.PlaneGeometry(L, W), new THREE.MeshStandardMaterial({ color: 0xd9d4c7 }));
  sol.rotation.x = -Math.PI / 2;
  sol.receiveShadow = true;
  scene.add(sol);

  const murFond = boite(L, H, 0.1, 0xf4f1ea);
  murFond.position.set(0, H / 2, -W / 2);
  scene.add(murFond);
  const murGauche = boite(0.1, H, W, 0xf4f1ea);
  murGauche.position.set(-L / 2, H / 2, 0);
  scene.add(murGauche);
  const murDroit = boite(0.1, H, W, 0xdfe6ee, { transparent: true, opacity: 0.25 });
  murDroit.position.set(L / 2, H / 2, 0);
  scene.add(murDroit);

  // Tableau
  const tableau = boite(4, 1.2, 0.05, 0x2f4f3f);
  tableau.position.set(-2, 1.55, -W / 2 + 0.08);
  scene.add(tableau);
  const bureauProf = boite(1.6, 0.75, 0.7, 0x8b6b4a);
  bureauProf.position.set(-2, 0.375, -W / 2 + 1.0);
  scene.add(bureauProf);

  // --- Tables et places ---
  const places = [];
  const xs = [-3.6, -2.2, -0.8, 0.6, 2.0, 3.4];
  const zs = [-1.5, -0.5, 0.5, 1.5, 2.5];
  for (const z of zs) {
    for (const x of xs) {
      const table = boite(1.1, 0.05, 0.5, 0xb08d64);
      table.position.set(x, 0.75, z);
      scene.add(table);
      const pied = boite(1.0, 0.7, 0.04, 0x7a6a58);
      pied.position.set(x, 0.37, z - 0.22);
      scene.add(pied);
      const chaise = boite(0.42, 0.45, 0.42, 0x555d66);
      chaise.position.set(x, 0.225, z + 0.5);
      scene.add(chaise);
      places.push({ x, z: z + 0.5, libre: true });
    }
  }

  // --- Porte et capteurs de comptage ---
  const porte = boite(0.06, 2.1, 1.0, 0x8b5a2b);
  porte.position.set(PORTE.x, 1.05, PORTE.z);
  scene.add(porte);
  const capteurs = new THREE.Group();
  [[0x2e86de, -0.25], [0xe67e22, 0], [0x8e44ad, 0.25]].forEach(([c, dz]) => {
    const b = boite(0.12, 0.08, 0.12, c, { emissive: c, emissiveIntensity: 0.3 });
    b.position.set(PORTE.x - 0.15, 2.32, PORTE.z + dz);
    capteurs.add(b);
  });
  scene.add(capteurs);
  const labelPorte = etiquette('');
  labelPorte.position.set(PORTE.x - 0.2, 2.75, PORTE.z);
  scene.add(labelPorte);

  // --- Lecteur de badge (côté couloir, à gauche de la porte) ---
  const lecteur = boite(0.05, 0.2, 0.13, 0x2b2f36);
  lecteur.position.set(PORTE.x + 0.08, 1.25, PORTE.z - 0.75);
  scene.add(lecteur);
  const voyantLecteur = boite(0.02, 0.05, 0.09, 0x1f6fd1, { emissive: 0x1f6fd1, emissiveIntensity: 0.5 });
  voyantLecteur.position.set(PORTE.x + 0.115, 1.31, PORTE.z - 0.75);
  scene.add(voyantLecteur);
  const labelLecteur = etiquette('');
  labelLecteur.position.set(PORTE.x + 0.2, 1.6, PORTE.z - 0.75);
  scene.add(labelLecteur);
  let derniersBadges = 0;
  let dernieresAlertes = 0;
  let flashBadge = 0;
  let flashAlerte = 0;

  // --- Fenêtre (mur gauche) ---
  const charniere = new THREE.Group();
  charniere.position.set(-L / 2 + 0.06, 1.5, -0.9);
  const vitre = boite(0.04, 1.2, 1.8, 0x9fc5e8, { transparent: true, opacity: 0.55, roughness: 0.1 });
  vitre.position.set(0, 0, 0.9);
  charniere.add(vitre);
  scene.add(charniere);
  const cadre = boite(0.05, 1.3, 1.9, 0xffffff, { transparent: true, opacity: 0.15 });
  cadre.position.set(-L / 2 + 0.03, 1.5, 0);
  scene.add(cadre);
  const labelFenetre = etiquette('', 'etiquette alerte');
  labelFenetre.position.set(-L / 2 + 0.3, 2.35, 0);
  scene.add(labelFenetre);

  // --- Ventilation (mur du fond) ---
  const grille = boite(1.2, 0.5, 0.06, 0x3a3f45);
  grille.position.set(2.8, 2.15, -W / 2 + 0.08);
  scene.add(grille);
  const helice = new THREE.Group();
  helice.position.set(2.8, 2.15, -W / 2 + 0.13);
  const matPales = new THREE.MeshStandardMaterial({ color: 0xcfd6dd });
  for (let i = 0; i < 4; i++) {
    const pale = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.07, 0.02), matPales);
    pale.position.x = 0.2;
    const bras = new THREE.Group();
    bras.rotation.z = (i * Math.PI) / 2;
    bras.add(pale);
    helice.add(bras);
  }
  scene.add(helice);
  const labelVentil = etiquette('');
  labelVentil.position.set(2.8, 2.65, -W / 2 + 0.2);
  scene.add(labelVentil);

  // --- Capteur de CO2 ---
  const boitierCO2 = boite(0.2, 0.25, 0.08, 0xffffff, { emissive: 0x3cb371, emissiveIntensity: 0.6 });
  boitierCO2.position.set(1.4, 1.6, -W / 2 + 0.1);
  scene.add(boitierCO2);
  const labelCO2 = etiquette('');
  labelCO2.position.set(1.4, 1.95, -W / 2 + 0.2);
  scene.add(labelCO2);

  // --- Volume d'air coloré selon le CO2 ---
  const air = new THREE.Mesh(
    new THREE.BoxGeometry(L - 0.2, H - 0.1, W - 0.2),
    new THREE.MeshBasicMaterial({ color: 0x3cb371, transparent: true, opacity: 0.08, depthWrite: false }),
  );
  air.position.y = H / 2;
  scene.add(air);

  // --- Particules d'air neuf ---
  const NB = 500;
  const positions = new Float32Array(NB * 3);
  const vitesses = new Float32Array(NB * 3);
  const ages = new Float32Array(NB).fill(999);
  const geoParticules = new THREE.BufferGeometry();
  geoParticules.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const particules = new THREE.Points(geoParticules, new THREE.PointsMaterial({
    color: 0xffffff, size: 0.06, transparent: true, opacity: 0.85, depthWrite: false,
  }));
  scene.add(particules);

  function emettre(i, source, intensite) {
    if (source === 'ventil') {
      positions[i * 3] = 2.8 + (Math.random() - 0.5) * 1.0;
      positions[i * 3 + 1] = 2.1 + (Math.random() - 0.5) * 0.3;
      positions[i * 3 + 2] = -W / 2 + 0.2;
      vitesses[i * 3] = (Math.random() - 0.5) * 0.3;
      vitesses[i * 3 + 1] = -0.25 - Math.random() * 0.2;
      vitesses[i * 3 + 2] = 1.2 * intensite + Math.random() * 0.3;
    } else {
      positions[i * 3] = -L / 2 + 0.2;
      positions[i * 3 + 1] = 1.2 + Math.random() * 0.6;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 1.6;
      vitesses[i * 3] = 1.4 + Math.random() * 0.4;
      vitesses[i * 3 + 1] = -0.2 + Math.random() * 0.1;
      vitesses[i * 3 + 2] = (Math.random() - 0.5) * 0.4;
    }
    ages[i] = 0;
  }

  // --- Étudiants ---
  const etudiants = [];   // { groupe, chemin, etape, place, sortie }
  const matCorps = COULEURS_ETUDIANTS.map(c => new THREE.MeshStandardMaterial({ color: c }));
  const matTete = new THREE.MeshStandardMaterial({ color: 0xf1c27d });

  function creerEtudiant() {
    const g = new THREE.Group();
    const corps = new THREE.Mesh(new THREE.CapsuleGeometry(0.17, 0.5, 4, 8),
      matCorps[Math.floor(Math.random() * matCorps.length)]);
    corps.position.y = 0.6;
    corps.castShadow = true;
    const tete = new THREE.Mesh(new THREE.SphereGeometry(0.13, 12, 10), matTete);
    tete.position.y = 1.12;
    tete.castShadow = true;
    g.add(corps, tete);
    return g;
  }

  function cheminVers(place) {
    return [
      new THREE.Vector3(PORTE.x + 0.8, 0, PORTE.z),
      new THREE.Vector3(PORTE.x - 0.6, 0, PORTE.z),
      new THREE.Vector3(4.4, 0, place.z),
      new THREE.Vector3(place.x, 0, place.z),
    ];
  }

  function ajouterEtudiant() {
    const libres = places.filter(p => p.libre);
    if (!libres.length) return;
    const place = libres[Math.floor(Math.random() * libres.length)];
    place.libre = false;
    const groupe = creerEtudiant();
    const chemin = cheminVers(place);
    groupe.position.copy(chemin[0]);
    scene.add(groupe);
    etudiants.push({ groupe, chemin, etape: 1, place, sortie: false, assis: false });
  }

  function retirerEtudiant() {
    const candidats = etudiants.filter(e => !e.sortie);
    if (!candidats.length) return;
    const e = candidats[Math.floor(Math.random() * candidats.length)];
    e.sortie = true;
    e.assis = false;
    e.chemin = cheminVers(e.place).reverse();
    e.etape = 1;
    e.place.libre = true;
  }

  function bougerEtudiants(dtReel) {
    const vitesse = 3.0; // m/s à l'écran
    for (let i = etudiants.length - 1; i >= 0; i--) {
      const e = etudiants[i];
      if (e.assis) continue;
      const cible = e.chemin[e.etape];
      const pos = e.groupe.position;
      const d = cible.clone().sub(pos);
      const pasMax = vitesse * dtReel;
      if (d.length() <= pasMax) {
        pos.copy(cible);
        e.etape += 1;
        if (e.etape >= e.chemin.length) {
          if (e.sortie) {
            scene.remove(e.groupe);
            etudiants.splice(i, 1);
          } else {
            e.assis = true;
            e.groupe.position.y = -0.28;
          }
        }
      } else {
        pos.add(d.normalize().multiplyScalar(pasMax));
        e.groupe.position.y = 0;
      }
    }
  }

  function redimensionner() {
    const w = conteneur.clientWidth;
    const h = conteneur.clientHeight;
    renderer.setSize(w, h);
    rendererLabels.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', redimensionner);
  redimensionner();

  let ouvertureFenetre = 0;

  // Mise à jour à chaque image
  function rendre(etat, dtReel) {
    // Nombre d'étudiants visibles = nombre réel dans la salle
    const presents = etudiants.filter(e => !e.sortie).length;
    if (presents < etat.N_reel) {
      for (let k = 0; k < Math.min(2, etat.N_reel - presents); k++) ajouterEtudiant();
    } else if (presents > etat.N_reel) {
      for (let k = 0; k < Math.min(2, presents - etat.N_reel); k++) retirerEtudiant();
    }
    bougerEtudiants(dtReel);

    // Air
    const couleur = couleurCO2(etat.Caffiche);
    air.material.color.copy(couleur);
    air.material.opacity = 0.05 + Math.min(0.2, Math.max(0, (etat.Caffiche - 420) / 8000));
    boitierCO2.material.emissive.copy(couleur);
    labelCO2.element.textContent = `CO₂ ${Math.round(etat.Caffiche)} ppm`;

    // Ventilation
    const enMarche = etat.niveau !== 'arret';
    const vitesseHelice = enMarche ? (etat.niveau === 'grande' ? 18 : 9) * (etat.pannes.ventilation ? 0.1 : 1) : 0;
    helice.rotation.z += vitesseHelice * dtReel;
    matPales.color.set(etat.pannes.ventilation && enMarche ? 0xc0392b : 0xcfd6dd);
    const texteNiveau = { arret: 'arrêt', petite: 'petite vitesse', grande: 'grande vitesse' }[etat.niveau];
    labelVentil.element.textContent = `Ventilation : ${texteNiveau}`;

    // Fenêtre
    const cible = etat.pannes.fenetre ? 1 : 0;
    ouvertureFenetre += (cible - ouvertureFenetre) * Math.min(1, dtReel * 3);
    charniere.rotation.y = -1.1 * ouvertureFenetre;
    labelFenetre.element.textContent = 'Fenêtre ouverte';
    labelFenetre.visible = etat.pannes.fenetre;

    // Porte
    labelPorte.element.textContent = etat.pannes.comptage
      ? `Porte : ${etat.N_mesure} comptés (${etat.N_reel} réels)`
      : `Porte : ${etat.N_mesure} personnes`;
    labelPorte.element.classList.toggle('alerte', etat.pannes.comptage);

    // Lecteur de badge : vert à chaque badge, rouge quand un badge et un passage ne collent pas
    if (etat.badges > derniersBadges) flashBadge = 0.4;
    if (etat.alertesBadge > dernieresAlertes) flashAlerte = 2;
    derniersBadges = etat.badges;
    dernieresAlertes = etat.alertesBadge;
    flashBadge = Math.max(0, flashBadge - dtReel);
    flashAlerte = Math.max(0, flashAlerte - dtReel);
    const couleurVoyant = flashAlerte > 0 ? 0xc0392b : flashBadge > 0 ? 0x2ecc71 : 0x1f6fd1;
    voyantLecteur.material.color.set(couleurVoyant);
    voyantLecteur.material.emissive.set(couleurVoyant);
    voyantLecteur.material.emissiveIntensity = flashAlerte > 0 || flashBadge > 0 ? 1.2 : 0.5;
    labelLecteur.element.textContent = etat.texteLecteur;
    labelLecteur.visible = etat.texteLecteur !== '';
    labelLecteur.element.classList.toggle('alerte', flashAlerte > 0);

    // Particules d'air neuf
    const intensiteVentil = enMarche ? (etat.niveau === 'grande' ? 1 : 0.6) * (etat.pannes.ventilation ? 0.12 : 1) : 0;
    let aEmettreV = Math.round(intensiteVentil * 3);
    let aEmettreF = etat.pannes.fenetre ? 3 : 0;
    for (let i = 0; i < NB; i++) {
      if (ages[i] > 4) {
        if (aEmettreV > 0) { emettre(i, 'ventil', intensiteVentil); aEmettreV--; continue; }
        if (aEmettreF > 0) { emettre(i, 'fenetre', 1); aEmettreF--; continue; }
        positions[i * 3 + 1] = -10; // cachée
        continue;
      }
      ages[i] += dtReel;
      positions[i * 3] += vitesses[i * 3] * dtReel;
      positions[i * 3 + 1] += vitesses[i * 3 + 1] * dtReel;
      positions[i * 3 + 2] += vitesses[i * 3 + 2] * dtReel;
      if (positions[i * 3 + 1] < 0.2) vitesses[i * 3 + 1] = Math.abs(vitesses[i * 3 + 1]) * 0.3;
    }
    geoParticules.attributes.position.needsUpdate = true;

    controles.update();
    renderer.render(scene, camera);
    rendererLabels.render(scene, camera);
  }

  function vider() {
    for (const e of etudiants) scene.remove(e.groupe);
    etudiants.length = 0;
    places.forEach(p => { p.libre = true; });
  }

  return { rendre, vider };
}
