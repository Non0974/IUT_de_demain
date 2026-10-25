// Vue 3D de tout le bâtiment : les étages côte à côte comme sur un plan, chaque salle colorée
// selon son occupation ou son air, avec des points pour les personnes.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { SALLES, ETAGES, LONGUEUR_BATIMENT, PROFONDEUR, COULOIR } from './batiment.js';

const ECART = 6;   // m entre deux étages posés côte à côte

const MAX_POINTS = 40;
const GRIS_LIBRE = new THREE.Color(0xdfe3e8);

function couleurOccupation(ratio) {
  // gris (vide) -> bleu clair -> bleu foncé (pleine)
  if (ratio <= 0) return GRIS_LIBRE.clone();
  return new THREE.Color(0xb9d3f2).lerp(new THREE.Color(0x1f5fb0), Math.min(1, ratio));
}

function couleurAir(ppm) {
  const pts = [[420, 0x3cb371], [800, 0xf4d03f], [1200, 0xe67e22], [1800, 0xc0392b]];
  if (ppm <= pts[0][0]) return new THREE.Color(pts[0][1]);
  for (let i = 1; i < pts.length; i++) {
    if (ppm <= pts[i][0]) {
      const a = (ppm - pts[i - 1][0]) / (pts[i][0] - pts[i - 1][0]);
      return new THREE.Color(pts[i - 1][1]).lerp(new THREE.Color(pts[i][1]), a);
    }
  }
  return new THREE.Color(pts[pts.length - 1][1]);
}

export function creerVueIut(conteneur, surClic) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  conteneur.appendChild(renderer.domElement);
  const rendererLabels = new CSS2DRenderer();
  rendererLabels.domElement.className = 'calque-etiquettes';
  conteneur.appendChild(rendererLabels.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe9edf2);
  const camera = new THREE.PerspectiveCamera(40, 1, 0.5, 400);
  const LARGEUR_ETAGE = COULOIR + 2 * PROFONDEUR + 1;
  const controles = new OrbitControls(camera, rendererLabels.domElement);
  controles.target.set(0, 0, 0);
  controles.maxPolarAngle = Math.PI / 2.1;
  controles.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0xb0b0b0, 1.7));
  const soleil = new THREE.DirectionalLight(0xffffff, 1.0);
  soleil.position.set(10, 30, 15);
  scene.add(soleil);

  // Plateaux et couloirs
  const groupesEtage = {};
  ETAGES.forEach(etage => {
    const g = new THREE.Group();
    const largeur = LARGEUR_ETAGE;
    const dalle = new THREE.Mesh(new THREE.BoxGeometry(LONGUEUR_BATIMENT + 1, 0.15, largeur),
      new THREE.MeshStandardMaterial({ color: 0xf6f4ef, transparent: true, opacity: 0.85 }));
    dalle.position.y = -0.1;
    g.add(dalle);
    const couloir = new THREE.Mesh(new THREE.BoxGeometry(LONGUEUR_BATIMENT, 0.02, COULOIR),
      new THREE.MeshStandardMaterial({ color: 0xcfc8b8 }));
    g.add(couloir);
    const div = document.createElement('div');
    div.className = 'etiquette etage';
    div.textContent = etage === 1 ? '1er étage' : `${etage}e étage`;
    const label = new CSS2DObject(div);
    label.position.set(0, 0.3, -largeur / 2 - 1.2);
    g.add(label);
    scene.add(g);
    groupesEtage[etage] = g;
  });

  // Salles
  const salles3d = {};
  const sols = [];
  const geoPoint = new THREE.SphereGeometry(0.22, 10, 8);
  const matPoint = new THREE.MeshStandardMaterial({ color: 0x24324a });
  for (const s of SALLES) {
    const g = groupesEtage[s.etage];
    const matSol = new THREE.MeshStandardMaterial({ color: GRIS_LIBRE });
    const sol = new THREE.Mesh(new THREE.BoxGeometry(s.largeur, 0.12, s.profondeur), matSol);
    sol.position.set(s.x, 0.06, s.z);
    sol.userData.id = s.id;
    g.add(sol);
    sols.push(sol);
    // murs bas, pour voir l'intérieur
    const murs = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(s.largeur, 1.0, s.profondeur)),
      new THREE.LineBasicMaterial({ color: 0x6b7480 }),
    );
    murs.position.set(s.x, 0.5, s.z);
    g.add(murs);
    const cadre = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(s.largeur + 0.2, 1.4, s.profondeur + 0.2)),
      new THREE.LineBasicMaterial({ color: 0xc0392b }),
    );
    cadre.position.set(s.x, 0.7, s.z);
    cadre.visible = false;
    g.add(cadre);
    // personnes : points sur une grille dans la salle
    const points = new THREE.InstancedMesh(geoPoint, matPoint, MAX_POINTS);
    const m = new THREE.Matrix4();
    const colonnes = 8;
    for (let i = 0; i < MAX_POINTS; i++) {
      const cx = (i % colonnes) / (colonnes - 1) - 0.5;
      const cz = Math.floor(i / colonnes) / (Math.ceil(MAX_POINTS / colonnes) - 1) - 0.5;
      m.makeTranslation(s.x + cx * (s.largeur - 1.4), 0.4, s.z + cz * (s.profondeur - 1.4));
      points.setMatrixAt(i, m);
    }
    points.count = 0;
    points.frustumCulled = false;
    g.add(points);
    const div = document.createElement('div');
    div.className = 'etiquette salle';
    const label = new CSS2DObject(div);
    label.position.set(s.x, 1.6, s.z);
    g.add(label);
    salles3d[s.id] = { matSol, points, cadre, div, salle: s };
  }

  // Clic sur une salle
  const rayon = new THREE.Raycaster();
  const souris = new THREE.Vector2();
  let depart = null;
  rendererLabels.domElement.addEventListener('pointerdown', e => { depart = [e.clientX, e.clientY]; });
  rendererLabels.domElement.addEventListener('pointerup', e => {
    if (!depart || Math.hypot(e.clientX - depart[0], e.clientY - depart[1]) > 5) return;   // c'était une rotation
    const r = renderer.domElement.getBoundingClientRect();
    souris.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    rayon.setFromCamera(souris, camera);
    const touche = rayon.intersectObjects(sols.filter(s => s.parent.visible))[0];
    if (touche) surClic(touche.object.userData.id);
  });

  // Étages côte à côte si la zone est large, l'un au-dessus de l'autre si elle est haute,
  // puis on recule la caméra juste assez pour tout voir
  function cadrer() {
    const cote = camera.aspect > 1.3;
    const n = ETAGES.length;
    ETAGES.forEach((etage, i) => {
      const decalage = i - (n - 1) / 2;
      groupesEtage[etage].position.set(cote ? decalage * (LONGUEUR_BATIMENT + ECART) : 0, 0, cote ? 0 : decalage * (LARGEUR_ETAGE + ECART));
    });
    const largeur = (cote ? n * (LONGUEUR_BATIMENT + ECART) : LONGUEUR_BATIMENT) + 4;
    const profondeur = (cote ? LARGEUR_ETAGE : n * (LARGEUR_ETAGE + ECART)) + 4;
    const vfov = THREE.MathUtils.degToRad(camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
    const distance = Math.max((largeur / 2) / Math.tan(hfov / 2), (profondeur / 2) / Math.tan(vfov / 2)) * 1.1;
    const direction = new THREE.Vector3(0, cote ? 0.82 : 0.92, cote ? 0.57 : 0.4).normalize();
    camera.position.copy(direction.multiplyScalar(distance));
    controles.target.set(0, 0, 0);
    controles.update();
  }

  function redimensionner() {
    const w = conteneur.clientWidth;
    const h = conteneur.clientHeight;
    renderer.setSize(w, h);
    rendererLabels.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    cadrer();
  }
  window.addEventListener('resize', redimensionner);
  redimensionner();

  // etat : { salles: {id: {personnes, co2, cours}}, mode, etage, selection, surligne: Set }
  function rendre(etat) {
    for (const etage of ETAGES) groupesEtage[etage].visible = etat.etage === 'tous' || etat.etage === etage;
    for (const [id, o] of Object.entries(salles3d)) {
      const e = etat.salles[id];
      const s = o.salle;
      const occupee = e.cours.length > 0;
      const co2 = e.co2 ?? 420;
      o.matSol.color.copy(etat.mode === 'air' ? couleurAir(co2) : couleurOccupation(e.personnes / s.places));
      o.points.count = Math.min(MAX_POINTS, e.personnes);
      o.cadre.visible = etat.selection === id || etat.surligne.has(id);
      o.cadre.material.color.set(etat.selection === id ? 0xc0392b : 0xe67e22);
      const texte = etat.mode === 'air'
        ? `${Math.round(co2)} ppm`
        : occupee ? `${e.personnes} / ${s.places}` : 'libre';
      o.div.innerHTML = `<b>${id}</b>${s.equipee ? ' ●' : ''}<br>${texte}`;
      o.div.classList.toggle('alerte', co2 >= 1200);
    }
    controles.update();
    renderer.render(scene, camera);
    rendererLabels.render(scene, camera);
  }

  return { rendre };
}
