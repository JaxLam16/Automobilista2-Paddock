// AMS2 Livery Editor: paint directly on the 3D car. See engine.js for how painting works on the GPU.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { computeBoundsTree, disposeBoundsTree, acceleratedRaycast } from 'three-mesh-bvh';
import { PaintEngine, PATTERNS, MAX_STOPS, rawColor } from './engine.js';
import * as ST from './stamps.js';

THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree;
THREE.Mesh.prototype.raycast = acceleratedRaycast;

// ================================================================================================
// helpers
// ================================================================================================
const $ = s => document.querySelector(s);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const V3 = a => new THREE.Vector3().fromArray(a);
const M = v => new THREE.Vector3(-v.x, v.y, v.z);                 // mirror across the car's centre line (object space)
const store = {
  get(k, d) { try { const v = localStorage.getItem('ams2le:' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('ams2le:' + k, JSON.stringify(v)); } catch {} },
};
function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'style') e.style.cssText = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (['value', 'checked', 'textContent', 'innerHTML', 'disabled', 'selected', 'title'].includes(k)) e[k] = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c instanceof Node ? c : String(c));
  return e;
}
async function api(path, opts) {
  if (opts?.method === 'POST' && typeof opts.body === 'string') opts = { ...opts, headers: { ...opts.headers, 'Content-Type': 'application/json' } };
  if (opts?.method === 'POST' && opts.body instanceof Blob) opts = { ...opts, headers: { ...opts.headers, 'Content-Type': 'application/octet-stream' } };
  const r = await fetch(path, opts);
  const ct = r.headers.get('content-type') || '';
  if (!r.ok) throw new Error(ct.includes('json') ? (await r.json()).error : `${r.status} ${r.statusText}`);
  return ct.includes('json') ? r.json() : r.blob();
}
let toastTimer;
function toast(msg, kind = '', ms = 4000) {
  const t = $('#toast'); t.textContent = msg; t.className = kind; t.style.display = 'block';
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.style.display = 'none'; }, ms);
}
function busy(text) {
  $('#busy').classList.toggle('show', !!text);
  if (text) $('#busyText').textContent = text;
  return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));     // let the overlay paint
}
const hex = c => '#' + rawColor(c).getHexString(THREE.LinearSRGBColorSpace);
const b64 = (s, T) => { const u = Uint8Array.from(atob(s), c => c.charCodeAt(0)); return new T(u.buffer); };
const cm = m => (m * 100 < 10 ? (m * 100).toFixed(1) : Math.round(m * 100)) + ' cm';
const pct = v => Math.round(v * 100) + '%';

// ================================================================================================
// settings (remembered between sessions)
// ================================================================================================
const TEXTURES = {
  carbon:    { name: 'Carbon fibre', type: 9, spacing: 0.06, c1: '#0b0c0e', c2: '#4a4e55' },
  forged:    { name: 'Forged carbon', type: 10, spacing: 0.16, c1: '#08090a', c2: '#62666d' },
  kevlar:    { name: 'Kevlar', type: 9, spacing: 0.06, c1: '#6b5208', c2: '#e3bb2c' },
  brushed:   { name: 'Brushed metal', type: 11, spacing: 0.4, c1: '#7d828a', c2: '#d4d7dc' },
  honeycomb: { name: 'Honeycomb mesh', type: 12, spacing: 0.03, c1: '#111214', c2: '#34373d', two: true, size: 0.6 },
};
const GRADIENT_PRESETS = {
  'Main → second': null, 'Fade out': null,
  Sunset: [['#2b0a3d', 0], ['#c2185b', 0.45], ['#ff6f00', 0.75], ['#ffd54f', 1]],
  Ocean: [['#001f3f', 0], ['#0074d9', 0.55], ['#7fdbff', 1]],
  Fire: [['#3b0000', 0], ['#e10600', 0.4], ['#ff8a00', 0.75], ['#ffe14d', 1]],
  Rainbow: [['#ff0000', 0], ['#ff9900', 0.17], ['#ffee00', 0.33], ['#33cc33', 0.5], ['#00aaff', 0.67], ['#3333ff', 0.83], ['#aa33ff', 1]],
  Chrome: [['#f5f7fa', 0], ['#8a9099', 0.35], ['#ffffff', 0.5], ['#5b616b', 0.7], ['#e9edf2', 1]],
  'Three bands': [['#009246', 0], ['#ffffff', 0.5], ['#ce2b37', 1]],
};
const FINISHES = [['Matte', 0, 0], ['Satin', 0.35, 0.2], ['Shiny', 0.7, 0.55], ['High gloss', 0.9, 0.85], ['Reflective', 1, 1]];
const DEFAULTS = {
  tool: 'brush', color: '#e10600', color2: '#ffffff', symmetry: false, recent: [],
  brush: { size: 0.04, hardness: 0.8, opacity: 1, protect: false, pressure: true },
  eraser: { size: 0.06, hardness: 0.85, opacity: 1, protect: false },
  line: { size: 0.015, hardness: 0.9, opacity: 1, protect: false },
  fill: { target: 'panel', with: 'colour', opacity: 1, scale: 1, angle: 0, c1: '#0b0c0e', c2: '#4a4e55' },
  gradient: { type: 'linear', target: 'panel', blend: 'smooth', repeat: 1, clip: false,
              stops: [{ pos: 0, color: '#e10600', alpha: 1 }, { pos: 1, color: '#111111', alpha: 1 }] },
  pattern: { type: 0, proj: 0, angle: 0, spacing: 0.12, size: 0.6, spread: 0, drop: 0, seed: 1, two: false, c1: '#111111', c2: '#ffffff',
             fadeDir: 0, fadeStart: 0.1, fadeEnd: 0.9, fadeShape: 'linear', fadeFx: 3, fadeCurve: 1, fadeA: null, fadeB: null,
             target: 'layer', opacity: 1, into: 'new' },
  pen: { width: 0.02 },
  shape: { ...ST.SHAPE_DEFAULTS },
  text: { ...ST.TEXT_DEFAULTS },
  image: { cut: { mode: 'off', tolerance: 18, feather: 8, connected: true }, tint: false, tintColor: '#ffffff' },
  customFonts: [],
};
function merge(a, b) {
  const out = structuredClone(a);
  for (const [k, v] of Object.entries(b || {})) {
    if (v && typeof v === 'object' && !Array.isArray(v) && out[k] && typeof out[k] === 'object' && !Array.isArray(out[k])) out[k] = merge(out[k], v);
    else if (k in out) out[k] = v;
  }
  return out;
}
const S = merge(DEFAULTS, store.get('settings', {}));
let saveTimer;
const saveSettings = () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => store.set('settings', { ...S, image: { ...S.image, current: S.image.current?.src?.startsWith('data:') ? undefined : S.image.current } }), 400); };

// ================================================================================================
// 3D view
// ================================================================================================
const view = $('#view');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.NeutralToneMapping;
view.prepend(renderer.domElement);
renderer.domElement.addEventListener('webglcontextlost', () => toast('The graphics card ran out of memory and the editor lost its picture. Reload the page (save first if you can), or open it with ?res=0.5 for half resolution.', 'err', 60000));
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x16181c);
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.9;
const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(3, 6, -4); scene.add(sun);
const floor = new THREE.Mesh(new THREE.CircleGeometry(7, 72), new THREE.MeshStandardMaterial({ color: 0x24272d, roughness: 0.95 }));
floor.rotation.x = -Math.PI / 2; scene.add(floor);
const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 200);
camera.position.set(-5.2, 1.9, -6.0);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.target.set(0, 0.55, 0); controls.zoomToCursor = true;
controls.maxPolarAngle = Math.PI * 0.495; controls.minDistance = 0.4; controls.maxDistance = 20;
controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE };
function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  $('#handles').setAttribute('viewBox', `0 0 ${w} ${h}`);
}
new ResizeObserver(resize).observe(view); resize();

// brush cursor rings (one per side when symmetry is on)
const ringMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.95, depthTest: false, side: THREE.DoubleSide });
const ringMat2 = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.55, depthTest: false, side: THREE.DoubleSide });
function makeRing() {
  const g = new THREE.Group();
  const a = new THREE.Mesh(new THREE.RingGeometry(0.955, 1, 72), ringMat), b = new THREE.Mesh(new THREE.RingGeometry(1, 1.04, 72), ringMat2);
  a.renderOrder = b.renderOrder = 999; g.add(a, b); g.visible = false; scene.add(g); return g;
}
const rings = [makeRing(), makeRing()];

// ================================================================================================
// car + paint geometry
// ================================================================================================
const MATS = [
  [['TREAD', 'TIRE', 'TYRE'], { color: 0x2c2d31, roughness: 0.82 }],
  [['GLASS', 'WINDOW', 'WINDSCREEN'], { color: 0x101418, roughness: 0.05, metalness: 0.2, transparent: true, opacity: 0.85 }],
  [['CARBON'], { color: 0x16181a, roughness: 0.45 }],
  [['WHEEL', 'RIM'], { color: 0x2a2c30, metalness: 0.7, roughness: 0.35 }],
  [['LIGHT'], { color: 0xd8dde4, roughness: 0.1, metalness: 0.4 }],
  [['DISC'], { color: 0x55585e, metalness: 0.8, roughness: 0.4 }],
];
const matCache = new Map();
function otherMaterial(name) {
  const hit = MATS.find(([keys]) => keys.some(k => name.includes(k)));
  const key = hit ? hit[0][0] : 'other';
  if (!matCache.has(key)) matCache.set(key, new THREE.MeshStandardMaterial(hit ? hit[1] : { color: 0x3a3d42, roughness: 0.6 }));
  return matCache.get(key);
}

let car = null;              // { id, name, group, meshes, paintGroups[], vIsl[], geo, bounds, info }
let engine = null;
let paintMat = null;

function buildCar(data) {
  const group = new THREE.Group(); group.scale.x = -1;           // Madness is left-handed; mirror so text reads correctly
  const meshes = [], paintGroups = [], vIsl = [], islandRange = [];
  const chunks = []; let islandBase = 0, nTri = 0;
  const q = new THREE.Quaternion(), off = new THREE.Vector3(), tmp = new THREE.Vector3();
  data.parts.forEach((p, pi) => {
    const pos = b64(p.pos, Float32Array), nrm = b64(p.nrm, Float32Array);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(b64(p.uv0, Float32Array), 2));
    const uv2 = b64(p.uv2, Float32Array);
    g.setAttribute('uv1', new THREE.BufferAttribute(uv2, 2));
    const arrays = p.groups.map(grp => b64(grp.index, Uint32Array));
    const idx = new Uint32Array(arrays.reduce((n, a) => n + a.length, 0));
    const paintSet = new Set(); let start = 0;
    arrays.forEach((a, i) => { idx.set(a, start); g.addGroup(start, a.length, i); if (p.groups[i].material.includes('PAINT')) paintSet.add(i); start += a.length; });
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    g.computeBoundsTree();                                          // (reorders triangles inside each group)
    const mesh = new THREE.Mesh(g, p.groups.map((grp, i) => paintSet.has(i) ? null : otherMaterial(grp.material)));
    mesh.position.fromArray(p.offset); mesh.quaternion.set(...p.quat);
    mesh.userData.part = pi;
    group.add(mesh); meshes.push(mesh); paintGroups.push(paintSet);
    // ---- paint triangles of this part, in car space, with panel (UV island) ids
    const nv = pos.length / 3, isl = new Int32Array(nv).fill(-1);
    vIsl.push(isl);
    if (!paintSet.size) return;
    const parent = new Int32Array(nv); for (let i = 0; i < nv; i++) parent[i] = i;
    const find = x => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    const tris = [];
    for (const grp of g.groups) {
      if (!paintSet.has(grp.materialIndex)) continue;
      for (let t = grp.start; t < grp.start + grp.count; t += 3) {
        const a = g.index.array[t], b = g.index.array[t + 1], c = g.index.array[t + 2];
        tris.push(a, b, c);
        const ra = find(a), rb = find(b); if (ra !== rb) parent[ra] = rb;
        const rb2 = find(b), rc = find(c); if (rb2 !== rc) parent[rb2] = rc;
      }
    }
    const ids = new Map();
    for (const v of tris) { const r = find(v); if (!ids.has(r)) ids.set(r, islandBase + ids.size); isl[v] = ids.get(r); }
    islandRange[pi] = [islandBase, islandBase + ids.size];
    islandBase += ids.size;
    q.set(...p.quat); off.fromArray(p.offset);
    const P = new Float32Array(nv * 3), N = new Float32Array(nv * 3);
    for (let i = 0; i < nv; i++) {
      tmp.fromArray(pos, i * 3).applyQuaternion(q).add(off).toArray(P, i * 3);
      tmp.fromArray(nrm, i * 3).applyQuaternion(q).normalize().toArray(N, i * 3);
    }
    chunks.push({ P, N, uv: uv2, isl, part: pi, tris });
    nTri += tris.length / 3;
  });
  // ---- one non-indexed geometry with every paint triangle (what the paint engine draws in UV space)
  const nV = nTri * 3;
  const position = new Float32Array(nV * 3), normal = new Float32Array(nV * 3), luv = new Float32Array(nV * 2);
  const island = new Float32Array(nV), part = new Float32Array(nV), tri = new Float32Array(nV * 4);
  const bounds = new THREE.Box3();
  let o = 0;
  for (const ch of chunks) {
    const { P, N, uv, isl, tris } = ch;
    for (let t = 0; t < tris.length; t += 3) {
      const vs = [tris[t], tris[t + 1], tris[t + 2]];
      let cx = 0, cy = 0, cz = 0, cu = 0, cv = 0;
      for (const v of vs) { cx += P[v * 3]; cy += P[v * 3 + 1]; cz += P[v * 3 + 2]; cu += uv[v * 2]; cv += uv[v * 2 + 1]; }
      cx /= 3; cy /= 3; cz /= 3; cu /= 3; cv /= 3;
      // some cars put triangles in other UV tiles (e.g. u 2..3): bring them back into 0..1
      const du = cu < -0.002 || cu > 1.002 ? Math.floor(cu) : 0, dv = cv < -0.002 || cv > 1.002 ? Math.floor(cv) : 0;
      let rad = 0;
      for (const v of vs) rad = Math.max(rad, Math.hypot(P[v * 3] - cx, P[v * 3 + 1] - cy, P[v * 3 + 2] - cz));
      for (const v of vs) {
        for (let k = 0; k < 3; k++) { position[o * 3 + k] = P[v * 3 + k]; normal[o * 3 + k] = N[v * 3 + k]; }
        luv[o * 2] = uv[v * 2] - du; luv[o * 2 + 1] = uv[v * 2 + 1] - dv;
        island[o] = isl[v]; part[o] = ch.part;
        tri[o * 4] = cx; tri[o * 4 + 1] = cy; tri[o * 4 + 2] = cz; tri[o * 4 + 3] = rad;
        bounds.expandByPoint(tmp.set(P[v * 3], P[v * 3 + 1], P[v * 3 + 2]));
        o++;
      }
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(position, 3));
  geo.setAttribute('normal', new THREE.BufferAttribute(normal, 3));
  geo.setAttribute('luv', new THREE.BufferAttribute(luv, 2));
  geo.setAttribute('island', new THREE.BufferAttribute(island, 1));
  geo.setAttribute('part', new THREE.BufferAttribute(part, 1));
  geo.setAttribute('tri', new THREE.BufferAttribute(tri, 4));
  return { group, meshes, paintGroups, vIsl, geo, bounds, islands: islandBase, islandRange, triangles: nTri };
}

function makePaintMaterial() {
  const m = new THREE.MeshPhysicalMaterial({ color: 0xffffff, map: engine.composite.texture, roughness: 0.3, metalness: 0,
                                             clearcoat: 1, clearcoatRoughness: 0.05 });
  m.defines = { DECODE_VIDEO_TEXTURE: '' };                          // the livery holds sRGB values: decode them in the shader
  m.onBeforeCompile = sh => {
    sh.uniforms.finishMap = { value: engine.finishRT.texture };
    sh.fragmentShader = 'uniform sampler2D finishMap;\n' + sh.fragmentShader
      .replace('#include <roughnessmap_fragment>', `
        vec4 finTex = texture2D(finishMap, vMapUv);
        float finGloss = finTex.r, finRefl = finTex.g;
        float roughnessFactor = mix(0.8, 0.12, finGloss);`)
      .replace('#include <lights_physical_fragment>', `#include <lights_physical_fragment>
        material.specularColor *= 0.25 + 0.75 * finRefl; material.specularF90 *= 0.25 + 0.75 * finRefl;
        #ifdef USE_CLEARCOAT
          material.clearcoat *= smoothstep(0.1, 1.0, finRefl * (0.35 + 0.65 * finGloss));
          material.clearcoatRoughness = clamp(0.03 + (1.0 - finGloss) * 0.45, 0.0525, 1.0);
        #endif`);
  };
  m.customProgramCacheKey = () => 'ams2-paint-1';
  return m;
}

// ================================================================================================
// picking
// ================================================================================================
const raycaster = new THREE.Raycaster(); raycaster.firstHitOnly = true;
const ndc = new THREE.Vector2();
function hitInfo(hit) {
  if (!hit) return null;
  const mesh = hit.object, pi = mesh.userData.part;
  const isPaint = car.paintGroups[pi].has(hit.face.materialIndex);
  const p = car.group.worldToLocal(hit.point.clone());
  const n = (hit.normal || hit.face.normal).clone().applyQuaternion(mesh.quaternion).normalize();
  return { isPaint, p, n, island: isPaint ? car.vIsl[pi][hit.face.a] : -1, part: pi, uv: hit.uv1, point: hit.point, distance: hit.distance };
}
function pick(x, y) {
  if (!car) return null;
  const r = renderer.domElement.getBoundingClientRect();
  ndc.set((x - r.left) / r.width * 2 - 1, -(y - r.top) / r.height * 2 + 1);
  camera.updateMatrixWorld();
  raycaster.setFromCamera(ndc, camera);
  raycaster.far = Infinity;
  return hitInfo(raycaster.intersectObjects(car.meshes, false)[0]);
}
/** Find the paint surface at a car-space point (used for the mirrored side). */
function pickObject(p, n) {
  if (!car) return null;
  const o = car.group.localToWorld(p.clone().addScaledVector(n, 0.06));
  raycaster.set(o, new THREE.Vector3(n.x, -n.y, -n.z).normalize());      // world direction of -n
  raycaster.far = 0.25;
  const h = hitInfo(raycaster.intersectObjects(car.meshes, false)[0]);
  raycaster.far = Infinity;
  return h?.isPaint ? h : null;
}
const toWorldDir = v => new THREE.Vector3(-v.x, v.y, v.z);
function camUpObject() { const u = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion); return new THREE.Vector3(-u.x, u.y, u.z); }
function toScreen(pObj) {
  const w = car.group.localToWorld(pObj.clone()).project(camera);
  return { x: (w.x + 1) / 2 * view.clientWidth, y: (1 - w.y) / 2 * view.clientHeight, behind: w.z > 1 };
}
function screenXY(e) { const r = view.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
const filterFor = (target, hit) => !hit ? undefined : target === 'panel' ? { island: hit.island } : target === 'part' ? { part: hit.part } : null;
const sameFilter = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
function mirroredFilter(target, hit) {
  if (target === 'layer' || !hit) return null;
  const f = filterFor(target, pickObject(M(hit.p), M(hit.n)));
  return f && !sameFilter(f, filterFor(target, hit)) ? f : null;
}

// ================================================================================================
// history (undo / redo)
// ================================================================================================
const hist = { undo: [], redo: [] };
const allRTs = new Set();
let projectDirty = false;
const reg = t => { if (t) allRTs.add(t); return t; };
function snap(L) {
  return { name: L.name, visible: L.visible, opacity: L.opacity, lock: L.lock, finishOnly: L.finishOnly, finish: L.finish ? [...L.finish] : null,
           params: L.params ? structuredClone(L.params) : undefined };
}
function restore(L, s) {
  Object.assign(L, { name: s.name, visible: s.visible, opacity: s.opacity, lock: s.lock, finishOnly: s.finishOnly, finish: s.finish ? [...s.finish] : null });
  if (s.params) { L.params = structuredClone(s.params); refreshDecal(L, true); }
}
function pushHistory(e) {
  hist.undo.push(e);
  for (const r of hist.redo) forget(r);
  hist.redo.length = 0;
  const limit = clamp(Math.floor(1.0e9 / engine.layerBytes()), 4, 40);
  const pixels = () => hist.undo.reduce((n, x) => n + countPix(x), 0);
  while (hist.undo.length > 1 && (pixels() > limit || hist.undo.length > 150)) forget(hist.undo.shift());
  gc(); projectDirty = true; updateUndoButtons();
}
const countPix = e => e.t === 'pixels' ? 1 : e.t === 'group' ? e.items.reduce((n, x) => n + countPix(x), 0) : 0;
function forget() {}
function gc() {
  const live = new Set();
  const addL = L => { if (L?.rt) live.add(L.rt); };
  engine.layers.forEach(addL);
  const visit = e => {
    if (e.t === 'pixels') { live.add(e.rt); addL(e.layer); }
    else if (e.t === 'layers') { e.before.forEach(addL); e.after.forEach(addL); }
    else if (e.t === 'group') e.items.forEach(visit);
    else if (e.layer) addL(e.layer);
  };
  hist.undo.forEach(visit); hist.redo.forEach(visit);
  for (const t of allRTs) if (!live.has(t)) { t.dispose(); allRTs.delete(t); }
}
function apply(e, undo) {
  if (e.t === 'pixels') { const cur = e.layer.rt; e.layer.rt = e.rt; e.rt = cur; }
  else if (e.t === 'props') restore(e.layer, undo ? e.before : e.after);
  else if (e.t === 'layers') {
    engine.layers = (undo ? e.before : e.after).slice();
    const want = undo ? e.activeBefore : e.activeAfter;
    if (want && engine.layers.includes(want) || !engine.layers.includes(engine.active)) engine.active = want || null;
  }
  else if (e.t === 'group') (undo ? [...e.items].reverse() : e.items).forEach(x => apply(x, undo));
}
function undo() {
  endEdit(); cancelPattern();
  const e = hist.undo.pop(); if (!e) return;
  apply(e, true); hist.redo.push(e); afterHistory();
}
function redo() {
  endEdit(); cancelPattern();
  const e = hist.redo.pop(); if (!e) return;
  apply(e, false); hist.undo.push(e); afterHistory();
}
function afterHistory() {
  if (engine.active && !engine.layers.includes(engine.active)) engine.active = engine.layers.at(-1) || null;
  projectDirty = true; markDirty(); renderLayers(); renderOptions(); updateUndoButtons();
}
function updateUndoButtons() { $('#undoBtn').disabled = !hist.undo.length; $('#redoBtn').disabled = !hist.redo.length; }
/** Record a change to the layer stack (add / delete / reorder). Call before changing engine.layers. */
function layersChange(fn, label) {
  const before = engine.layers.slice(), activeBefore = engine.active;
  fn();
  const e = { t: 'layers', before, after: engine.layers.slice(), activeBefore, activeAfter: engine.active, label };
  return e;
}

// coalesced edits of one layer's properties (slider drags, typing)
let pendingEdit = null;
function editLayer(L, fn, final = true, regen = false) {
  if (pendingEdit && pendingEdit.layer !== L) endEdit();
  if (!pendingEdit) pendingEdit = { layer: L, before: snap(L) };
  fn(L);
  if (L.kind === 'decal') refreshDecal(L, regen);
  markDirty();
  if (final) endEdit();
}
function endEdit() {
  if (!pendingEdit) return;
  const { layer, before } = pendingEdit; pendingEdit = null;
  const after = snap(layer);
  if (JSON.stringify(after) !== JSON.stringify(before)) pushHistory({ t: 'props', layer, before, after });
  renderLayers(false);
}

// ================================================================================================
// layers
// ================================================================================================
const active = () => engine?.active || null;
const markDirty = () => { needs.composite = true; needs.finish = true; };
const needs = { composite: true, finish: true, dilate: 0 };
let baseSelected = false;

function indexAbove(L = active()) { const i = engine.layers.indexOf(L); return i < 0 ? engine.layers.length : i + 1; }
function addPaintLayer(name = 'Paint', index = indexAbove(), record = true) {
  let L;
  const e = layersChange(() => { L = engine.addLayer(uniqueName(name), index); reg(L.rt); engine.active = L; });
  if (record) pushHistory(e);
  renderLayers(); return L;
}
function uniqueName(base) {
  const names = new Set(engine.layers.map(l => l.name));
  if (!names.has(base)) return base;
  for (let i = 2; ; i++) if (!names.has(`${base} ${i}`)) return `${base} ${i}`;
}
function ensurePaintLayer() {
  const L = active();
  if (L && L.kind === 'paint') return L;
  if (baseSelected) return basePaintLayer();
  return addPaintLayer('Paint');
}
/** With "Car base" selected, brush / fill / gradient / pattern go on a layer right above the base, under everything else. */
const isBasePaint = L => L?.kind === 'paint' && /^Base paint/.test(L.name);
function basePaintLayer() {
  baseSelected = false;
  if (isBasePaint(engine.layers[0])) { engine.active = engine.layers[0]; renderLayers(); renderOptions(); return engine.active; }
  const others = engine.layers.length;
  const L = addPaintLayer('Base paint', 0);
  renderOptions();
  toast(others ? 'Painting the base on a new "Base paint" layer, under all your other layers' : 'Painting the base on a new "Base paint" layer', 'ok', 4500);
  return L;
}
/** Lock transparency on a layer with nothing on it hides everything you paint: say so instead of doing nothing. */
function warnLockedEmpty(L) {
  if (!L?.lock || L.kind !== 'paint' || engine.hasPaint(L)) return false;
  toast(`"${L.name}" has Lock transparency on and nothing on it yet, so nothing shows. Untick Lock transparency under Layers.`, 'err', 7000);
  return true;
}
const TOOL_FOR = { text: 'text', shape: 'shape', image: 'image', path: 'pen' };
function setActive(L, { switchTool = true } = {}) {
  if (pen.drawing && L !== active()) finishPath();
  endEdit();
  const patterning = S.tool === 'pattern';
  if (L !== active()) { cancelPattern({ keepSelection: patterning }); pen.sel = null; if (patterning && L?.kind === 'paint') pat.target = L; }
  engine.active = L; baseSelected = !L;
  if (L?.kind === 'decal' && switchTool && S.tool !== 'select' && S.tool !== TOOL_FOR[L.params.type]) setTool(TOOL_FOR[L.params.type], { keepSelection: true });
  renderLayers(); renderOptions();
  if (patterning && S.tool === 'pattern') previewPattern();
}
function deleteLayer(L = active()) {
  if (!L) return;
  const i = engine.layers.indexOf(L);
  pushHistory(layersChange(() => { engine.layers.splice(i, 1); engine.active = engine.layers[Math.min(i, engine.layers.length - 1)] || null; }));
  markDirty(); renderLayers(); renderOptions();
}
function duplicateLayer(L = active()) {
  if (!L) return;
  const copy = engine.duplicate(L); reg(copy.rt);
  if (L.kind === 'decal') { copy.params = structuredClone(L.params); copy.decal = { tex: null, frames: [] }; refreshDecal(copy, true); }
  pushHistory(layersChange(() => { engine.layers.splice(engine.layers.indexOf(L) + 1, 0, copy); engine.active = copy; }));
  markDirty(); renderLayers(); renderOptions();
}
function moveLayer(L, dir) {
  const i = engine.layers.indexOf(L), j = i + dir;
  if (!L || j < 0 || j >= engine.layers.length) return;
  pushHistory(layersChange(() => { engine.layers.splice(i, 1); engine.layers.splice(j, 0, L); }));
  markDirty(); renderLayers();
}
function mergeDown(L = active()) {
  const i = engine.layers.indexOf(L), lower = engine.layers[i - 1];
  if (!L || !lower) return;
  if (lower.kind !== 'paint') return toast('The layer below is a text/shape/image layer. Rasterize it first, or move this layer.', 'err');
  const before = reg(engine.mergeDown(L, lower));
  const px = { t: 'pixels', layer: lower, rt: before };
  const lc = layersChange(() => { engine.layers.splice(i, 1); engine.active = lower; });
  pushHistory({ t: 'group', items: [px, lc] });
  if (JSON.stringify(L.finish) !== JSON.stringify(lower.finish)) toast(`Merged. The merged part now has the finish of "${lower.name}".`, '', 4000);
  markDirty(); renderLayers(); renderOptions();
}
function rasterizeLayer(L = active()) {
  if (!L || L.kind !== 'decal') return;
  const P = engine._layer({ name: L.name, kind: 'paint', rt: reg(engine.rasterize(L)), opacity: L.opacity, visible: L.visible, finish: L.finish ? [...L.finish] : null });
  pushHistory(layersChange(() => { engine.layers.splice(engine.layers.indexOf(L), 1, P); engine.active = P; }));
  markDirty(); renderLayers(); renderOptions();
}

const KIND = L => L.kind === 'paint' ? (L.finishOnly ? '✦' : '✎') : ({ text: 'T', shape: '◆', image: '▣', path: '✒' })[L.params?.type] || '?';
function renderLayers(full = true) {
  if (!engine) return;
  const list = $('#layerList'); list.innerHTML = '';
  for (let i = engine.layers.length - 1; i >= 0; i--) {
    const L = engine.layers[i];
    const meta = [L.opacity < 1 ? pct(L.opacity) : '', L.lock ? '🔒' : '', L.params?.mirror ? '⇋' : '',
                  L.finish ? finishName(L.finish) : ''].filter(Boolean).join(' ');
    const row = el('div', { class: 'layer' + (L === active() ? ' active' : ''), title: L.name },
      el('button', { class: 'eye' + (L.visible ? '' : ' off'), title: 'Show / hide', onclick: ev => { ev.stopPropagation();
        editLayer(L, x => { x.visible = !x.visible; }); renderLayers(); } }, '👁'),
      el('span', { class: 'kind' }, KIND(L)),
      el('span', { class: 'name' }, L.name),
      el('span', { class: 'meta' }, meta));
    row.addEventListener('click', () => setActive(L));
    row.addEventListener('dblclick', () => renameLayer(L, row.querySelector('.name')));
    list.append(row);
  }
  const base = el('div', { class: 'layer base' + (baseSelected ? ' active' : '') },
    el('span', { class: 'eye', style: `background:${hex(engine.background)};border-radius:4px;width:18px;height:18px;border:1px solid #555` }),
    el('span', { class: 'name' }, 'Car base'), el('span', { class: 'meta' }, finishName(engine.baseFinish)));
  base.addEventListener('click', () => { if (!baseSelected || active()) setActive(null); });
  list.append(base);
  const L = active();
  $('#dupLayerBtn').disabled = $('#delLayerBtn').disabled = !L;
  $('#mergeLayerBtn').disabled = !L || engine.layers.indexOf(L) < 1;
  $('#upLayerBtn').disabled = !L || engine.layers.indexOf(L) >= engine.layers.length - 1;
  $('#downLayerBtn').disabled = !L || engine.layers.indexOf(L) < 1;
  if (full) renderLayerProps();
}
function renameLayer(L, span) {
  const inp = el('input', { type: 'text', value: L.name, style: 'width:100%' });
  span.replaceWith(inp); inp.focus(); inp.select();
  const done = ok => { if (ok && inp.value.trim()) editLayer(L, x => { x.name = inp.value.trim(); }); renderLayers(); };
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') done(true); if (e.key === 'Escape') done(false); e.stopPropagation(); });
  inp.addEventListener('blur', () => done(true));
}
const finishName = f => (FINISHES.find(([, g, r]) => Math.abs(g - f[0]) < 0.02 && Math.abs(r - f[1]) < 0.02) || ['Custom'])[0];

function finishControls(get, set, inherit = false) {
  const f = get();                                                    // null = same as the car base
  const eff = () => get() || engine.baseFinish;
  const wrap = el('div');
  wrap.append(el('div', { class: 'seg' },
    inherit ? el('button', { class: f ? '' : 'on', title: 'Use the finish of the car base', onclick: () => set(null, true) }, 'Same as car') : null,
    FINISHES.map(([name, g, r]) => el('button', { class: f && finishName(f) === name || !inherit && finishName(eff()) === name ? 'on' : '', onclick: () => set([g, r], true) }, name))));
  wrap.append(slider('Gloss', () => eff()[0], (v, fin) => set([v, eff()[1]], fin), { min: 0, max: 1, step: 0.01, fmt: pct }));
  wrap.append(slider('Reflection', () => eff()[1], (v, fin) => set([eff()[0], v], fin), { min: 0, max: 1, step: 0.01, fmt: pct }));
  return wrap;
}
function renderLayerProps() {
  const box = $('#layerProps'); box.innerHTML = '';
  if (!engine) return;
  const L = active();
  if (!L) {
    box.append(el('h3', {}, 'Car base'));
    box.append(row('Base colour', colorButton(() => hex(engine.background), c => { engine.background = rawColor(c); projectDirty = true; markDirty(); renderLayers(false); })));
    box.append(el('h4', {}, 'Finish of the bare car'));
    box.append(finishControls(() => engine.baseFinish, (f, fin) => { engine.baseFinish = f; projectDirty = true; markDirty(); if (fin) renderLayers(); }));
    box.append(finishNote());
    box.append(el('div', { class: 'note', style: 'margin-top:8px' }, 'For a gradient, pattern or carbon base: keep Car base selected and use the Gradient, Patterns or Paint bucket tool. It goes on a "Base paint" layer under everything else.'));
    return;
  }
  box.append(el('h3', {}, L.kind === 'paint' ? (L.finishOnly ? 'Finish layer' : 'Paint layer') : ({ text: 'Text', shape: 'Shape', image: 'Image', path: 'Path' })[L.params.type] + ' layer'));
  box.append(slider('Opacity', () => L.opacity, (v, fin) => editLayer(L, x => { x.opacity = v; }, fin), { min: 0, max: 1, step: 0.01, fmt: pct }));
  if (L.kind === 'paint') {
    box.append(check('Lock transparency (paint only where this layer already has paint)', L.lock, v => editLayer(L, x => { x.lock = v; })));
    box.append(check('Finish only (changes gloss, not colour)', L.finishOnly, v => { editLayer(L, x => { x.finishOnly = v; }); renderLayers(); }));
  } else {
    box.append(el('button', { onclick: () => rasterizeLayer(L), title: 'Turn into a paint layer so you can erase or brush over it' }, 'Convert to paint layer'));
  }
  box.append(el('h4', {}, 'Finish'));
  box.append(finishControls(() => L.finish, (f, fin) => { editLayer(L, x => { x.finish = f; }, fin); if (fin) renderLayers(); }, true));
  box.append(finishNote());
}
function finishNote() {
  const f = car?.info?.finish;
  if (!f) return el('span');
  return el('div', { class: 'note' + (f.supported ? '' : ' warn') }, f.supported
    ? 'Gloss and reflection are saved to the game as a finish map.'
    : `Preview only on this car: ${f.reason}`);
}

// ================================================================================================
// small UI builders
// ================================================================================================
function row(label, ...kids) { return el('div', { class: 'row' }, el('label', {}, label), ...kids); }
function slider(label, get, set, { min, max, step = 0.01, fmt = v => v, log = false } = {}) {
  const toS = v => log ? Math.log(v / min) / Math.log(max / min) : v, fromS = s => log ? min * Math.pow(max / min, s) : s;
  const val = el('span', { class: 'val' }, fmt(get()));
  const inp = el('input', { type: 'range', class: 'fill', min: log ? 0 : min, max: log ? 1 : max, step: log ? 0.001 : step, value: toS(get()) });
  inp.addEventListener('input', () => { const v = fromS(+inp.value); set(v, false); val.textContent = fmt(v); });
  inp.addEventListener('change', () => { const v = fromS(+inp.value); set(v, true); val.textContent = fmt(v); });
  const r = row(label, inp, val);
  r.refresh = () => { inp.value = toS(get()); val.textContent = fmt(get()); };
  return r;
}
function seg(label, options, get, set) {
  const wrap = el('div', { class: 'seg' });
  const draw = () => { wrap.innerHTML = ''; for (const [v, name] of options) wrap.append(el('button', { class: get() === v ? 'on' : '', onclick: () => { set(v); draw(); } }, name)); };
  draw();
  return label ? el('div', {}, el('div', { class: 'note', style: 'margin:8px 0 4px' }, label), wrap) : wrap;
}
function check(label, value, set) {
  const inp = el('input', { type: 'checkbox', checked: value, onchange: e => set(e.target.checked) });
  return el('label', { class: 'check' }, inp, label);
}
function colour(label, get, set) { return row(label, colorButton(get, set, { title: label })); }

// ---- colour picker: our own, so "From car" reads the paint itself, not the lit and reflective pixels -----
const picker = { el: null, cb: null, h: 0, s: 0, v: 0, orig: '#000000', anchor: null };
function hexToRgb(h) { h = String(h).replace('#', ''); if (h.length === 3) h = [...h].map(c => c + c).join(''); const n = parseInt(h, 16) || 0; return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
const rgbToHex = (r, g, b) => '#' + [r, g, b].map(v => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')).join('');
function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, mx ? d / mx : 0, mx];
}
function hsvToRgb(h, s, v) { const f = n => { const k = (n + h / 60) % 6; return (v - v * s * Math.max(0, Math.min(k, 4 - k, 1))) * 255; }; return [f(5), f(3), f(1)]; }
const pickerValue = () => rgbToHex(...hsvToRgb(picker.h, picker.s, picker.v));
function openPicker(anchor, value, cb) {
  const box = picker.el || buildPicker();
  picker.cb = cb; picker.anchor = anchor; picker.orig = value;
  [picker.h, picker.s, picker.v] = rgbToHsv(...hexToRgb(value));
  box.style.display = 'block';
  const r = anchor.getBoundingClientRect(), bw = box.offsetWidth, bh = box.offsetHeight;
  let x = r.left, y = r.bottom + 6;
  if (x + bw > innerWidth - 8) x = innerWidth - bw - 8;
  if (y + bh > innerHeight - 8) y = Math.max(8, r.top - bh - 6);
  box.style.left = x + 'px'; box.style.top = y + 'px';
  drawPicker();
}
function closePicker() { if (picker.el) picker.el.style.display = 'none'; picker.cb = null; picker.anchor = null; }
function pickerSet(final) { const c = pickerValue(); picker.cb?.(c, final); if (final) addRecent(c); drawPicker(); }
function buildPicker() {
  const sv = el('canvas', { width: 224, height: 140, class: 'pkSV' }), hue = el('canvas', { width: 224, height: 14, class: 'pkHue' });
  const hexIn = el('input', { type: 'text', class: 'pkHex', spellcheck: 'false' });
  const swOld = el('span', { class: 'pkSw', title: 'Previous colour (click to go back)' }), swNew = el('span', { class: 'pkSw' });
  const rec = el('div', { class: 'recent' });
  const box = el('div', { id: 'picker' }, sv, hue,
    el('div', { class: 'pkRow' }, swOld, swNew, hexIn,
      el('button', { title: 'Pick a colour from the car: the paint itself, ignoring gloss and reflections', onclick: () => startPickFromCar(picker.cb) }, '⌖ From car')),
    rec);
  box.addEventListener('pointerdown', e => e.stopPropagation());
  const dragOn = (cv, fn) => cv.addEventListener('pointerdown', e => {
    cv.setPointerCapture(e.pointerId); fn(e);
    const mv = ev => fn(ev), up = ev => { fn(ev); cv.removeEventListener('pointermove', mv); cv.removeEventListener('pointerup', up); pickerSet(true); };
    cv.addEventListener('pointermove', mv); cv.addEventListener('pointerup', up);
  });
  dragOn(sv, e => { const r = sv.getBoundingClientRect(); picker.s = clamp((e.clientX - r.left) / r.width, 0, 1); picker.v = 1 - clamp((e.clientY - r.top) / r.height, 0, 1); pickerSet(false); });
  dragOn(hue, e => { const r = hue.getBoundingClientRect(); picker.h = clamp((e.clientX - r.left) / r.width, 0, 0.9999) * 360; pickerSet(false); });
  hexIn.addEventListener('change', () => { const v = hexIn.value.trim(); if (/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v)) { [picker.h, picker.s, picker.v] = rgbToHsv(...hexToRgb(v)); pickerSet(true); } });
  hexIn.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') hexIn.dispatchEvent(new Event('change')); if (e.key === 'Escape') closePicker(); });
  swOld.addEventListener('click', () => { [picker.h, picker.s, picker.v] = rgbToHsv(...hexToRgb(picker.orig)); pickerSet(true); });
  Object.assign(picker, { el: box, sv, hue, hexIn, swNew, swOld, rec });
  document.body.append(box);
  addEventListener('pointerdown', e => { if (picker.el.style.display === 'block' && !picker.anchor?.contains(e.target)) closePicker(); });
  return box;
}
function drawPicker() {
  const { sv, hue } = picker, g = sv.getContext('2d'), W = sv.width, Hh = sv.height;
  g.fillStyle = rgbToHex(...hsvToRgb(picker.h, 1, 1)); g.fillRect(0, 0, W, Hh);
  let gr = g.createLinearGradient(0, 0, W, 0); gr.addColorStop(0, '#fff'); gr.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = gr; g.fillRect(0, 0, W, Hh);
  gr = g.createLinearGradient(0, 0, 0, Hh); gr.addColorStop(0, 'rgba(0,0,0,0)'); gr.addColorStop(1, '#000'); g.fillStyle = gr; g.fillRect(0, 0, W, Hh);
  const x = picker.s * W, y = (1 - picker.v) * Hh;
  g.lineWidth = 2; g.strokeStyle = '#fff'; g.beginPath(); g.arc(x, y, 6, 0, Math.PI * 2); g.stroke();
  g.lineWidth = 1; g.strokeStyle = '#000'; g.beginPath(); g.arc(x, y, 7.5, 0, Math.PI * 2); g.stroke();
  const h = hue.getContext('2d'), hg = h.createLinearGradient(0, 0, hue.width, 0);
  for (let i = 0; i <= 6; i++) hg.addColorStop(i / 6, `hsl(${i * 60},100%,50%)`);
  h.fillStyle = hg; h.fillRect(0, 0, hue.width, hue.height);
  const hx = picker.h / 360 * hue.width; h.fillStyle = '#fff'; h.fillRect(hx - 2, 0, 4, hue.height); h.strokeStyle = '#000'; h.strokeRect(hx - 2.5, 0.5, 5, hue.height - 1);
  const c = pickerValue();
  if (document.activeElement !== picker.hexIn) picker.hexIn.value = c;
  picker.swNew.style.background = c; picker.swOld.style.background = picker.orig;
  picker.rec.innerHTML = '';
  for (const rc of S.recent) picker.rec.append(el('button', { style: `background:${rc}`, title: rc, onclick: () => { [picker.h, picker.s, picker.v] = rgbToHsv(...hexToRgb(rc)); pickerSet(true); } }));
}
let pickFromCar = null;
function startPickFromCar(cb) {
  if (!cb) return;
  pickFromCar = cb; closePicker();
  $('#hint').textContent = 'Click the car to pick the paint colour there (Esc to cancel)';
}
function endPickFromCar() { pickFromCar = null; $('#hint').textContent = HINTS[S.tool] || ''; }
function colorButton(get, set, { title = '', big = false } = {}) {
  const b = el('button', { class: 'swatch' + (big ? ' big' : ''), title: title || 'Choose a colour', style: `background:${get()}` });
  b.addEventListener('click', e => {
    e.stopPropagation();
    if (picker.el?.style.display === 'block' && picker.anchor === b) return closePicker();
    openPicker(b, get(), (c, fin) => { set(c, fin); b.style.background = c; });
  });
  return b;
}
/** The livery colour at a point on the car (what is painted, not how it is lit). */
function paintColourAt(hit) {
  engine.render(); needs.dilate = performance.now();
  const px = engine.sample(hit.uv);
  return rgbToHex(px[0], px[1], px[2]);
}
function addRecent(c) {
  c = c.toLowerCase(); S.recent = [c, ...S.recent.filter(x => x !== c)].slice(0, 16); saveSettings();
  const r = $('#recentColours'); if (r) r.replaceWith(recentRow());
}
function recentRow() {
  return el('div', { class: 'recent', id: 'recentColours' }, S.recent.map(c => el('button', { style: `background:${c}`, title: c + '  (right-click: secondary)',
    onclick: () => setColour(c), oncontextmenu: e => { e.preventDefault(); S.color2 = c; saveSettings(); renderOptions(); } })));
}
function setColour(c, second = false) {
  if (second) S.color2 = c; else S.color = c;
  saveSettings(); renderOptions();
  if (S.tool === 'pattern') previewPattern();
}
function colourBlock() {
  return el('div', {},
    el('div', { class: 'colours' },
      colorButton(() => S.color, c => { S.color = c; saveSettings(); }, { title: 'Main colour', big: true }),
      colorButton(() => S.color2, c => { S.color2 = c; saveSettings(); }, { title: 'Second colour', big: true }),
      el('button', { title: 'Swap colours', onclick: () => { [S.color, S.color2] = [S.color2, S.color]; saveSettings(); renderOptions(); } }, '⇄'),
      el('input', { type: 'text', value: S.color, style: 'width:82px', title: 'Hex colour', onchange: e => { const v = e.target.value.trim(); if (/^#?[0-9a-f]{6}$/i.test(v)) setColour(v.startsWith('#') ? v : '#' + v); } })),
    recentRow());
}

// ---- gradient editor: any number of colour stops -------------------------------------------------
let gSel = 0;
function sampleStops(st, t) {
  if (t <= st[0].pos) return { ...st[0] };
  for (let i = 1; i < st.length; i++) if (t <= st[i].pos) {
    const a = st[i - 1], b = st[i], f = (t - a.pos) / Math.max(1e-6, b.pos - a.pos), ca = hexToRgb(a.color), cb = hexToRgb(b.color);
    return { color: rgbToHex(...ca.map((v, k) => v + (cb[k] - v) * f)), alpha: a.alpha + (b.alpha - a.alpha) * f };
  }
  return { ...st.at(-1) };
}
function gradientCss(o) {
  const st = o.stops.slice().sort((a, b) => a.pos - b.pos), rep = o.repeat || 1;
  const col = s => `rgba(${hexToRgb(s.color).join(',')},${s.alpha})`, at = v => (v * 100 / rep).toFixed(2) + '%';
  const parts = o.blend === 'hard' ? st.flatMap((s, i) => [`${col(s)} ${at(s.pos)}`, `${col(s)} ${at(st[i + 1]?.pos ?? 1)}`]) : st.map(s => `${col(s)} ${at(s.pos)}`);
  return `${rep > 1 ? 'repeating-' : ''}linear-gradient(90deg, ${parts.join(', ')}), repeating-conic-gradient(#555 0 25%, #888 0 50%) 0 0/10px 10px`;
}
function gradientEditor(o, onChange) {
  const bar = el('div', { class: 'gBar', title: 'Click to add a colour' }), marks = el('div', { class: 'gMarks' }), detail = el('div');
  if (gSel >= o.stops.length) gSel = 0;
  const draw = () => {
    bar.style.background = gradientCss(o);
    marks.innerHTML = '';
    o.stops.forEach((s, i) => {
      const m = el('div', { class: 'gStop' + (i === gSel ? ' on' : ''), style: `left:${s.pos * 100}%;--c:${s.color}`, title: 'Drag to move · double-click to remove' });
      m.addEventListener('pointerdown', e => {
        e.preventDefault(); gSel = i; m.setPointerCapture(e.pointerId);
        const r = marks.getBoundingClientRect();
        const mv = ev => { s.pos = clamp((ev.clientX - r.left) / r.width, 0, 1); m.style.left = s.pos * 100 + '%'; bar.style.background = gradientCss(o); onChange(false); };
        const up = () => { m.removeEventListener('pointermove', mv); m.removeEventListener('pointerup', up); onChange(true); draw(); drawDetail(); };
        m.addEventListener('pointermove', mv); m.addEventListener('pointerup', up);
        marks.querySelectorAll('.gStop').forEach(x => x.classList.toggle('on', x === m)); drawDetail();
      });
      m.addEventListener('dblclick', () => { if (o.stops.length > 2) { o.stops.splice(i, 1); gSel = 0; onChange(true); draw(); drawDetail(); } });
      marks.append(m);
    });
  };
  bar.addEventListener('click', e => {
    if (o.stops.length >= MAX_STOPS) return toast(`Up to ${MAX_STOPS} colours`);
    const r = bar.getBoundingClientRect(), pos = clamp((e.clientX - r.left) / r.width, 0, 1);
    const c = sampleStops(o.stops.slice().sort((a, b) => a.pos - b.pos), (pos * (o.repeat || 1)) % 1 || pos);
    o.stops.push({ pos, color: c.color, alpha: c.alpha }); gSel = o.stops.length - 1; onChange(true); draw(); drawDetail();
  });
  const drawDetail = () => {
    detail.innerHTML = '';
    const s = o.stops[gSel]; if (!s) return;
    detail.append(row('Colour', colorButton(() => s.color, (c, fin) => { s.color = c; onChange(fin); draw(); })));
    detail.append(slider('Opacity', () => s.alpha, (v, fin) => { s.alpha = v; onChange(fin); draw(); }, { min: 0, max: 1, fmt: pct }));
    detail.append(slider('Position', () => s.pos, (v, fin) => { s.pos = v; onChange(fin); draw(); }, { min: 0, max: 1, step: 0.001, fmt: pct }));
    detail.append(el('div', { class: 'seg', style: 'margin:6px 0' },
      el('button', { disabled: o.stops.length <= 2, onclick: () => { o.stops.splice(gSel, 1); gSel = 0; onChange(true); draw(); drawDetail(); } }, 'Remove colour'),
      el('button', { onclick: () => { o.stops.forEach(x => { x.pos = 1 - x.pos; }); onChange(true); draw(); drawDetail(); } }, 'Reverse'),
      el('button', { onclick: () => { o.stops.slice().sort((a, b) => a.pos - b.pos).forEach((x, k, a) => { x.pos = k / (a.length - 1); }); onChange(true); draw(); drawDetail(); } }, 'Even spacing')));
  };
  draw(); drawDetail();
  return el('div', { class: 'gEd' }, bar, marks,
    el('div', { class: 'note', style: 'margin:2px 0 6px' }, 'Click the bar to add colours · drag the markers to space them · double-click one to remove it'), detail);
}

// ================================================================================================
// decals (text, shapes, images): editable layers projected onto the car
// ================================================================================================
const srcCache = new Map();
async function sourceCanvas(src) {
  if (!srcCache.has(src)) srcCache.set(src, (async () => {
    const img = await ST.loadImage(src);
    const isSvg = /\.svg($|\?)/i.test(src) || src.startsWith('data:image/svg');
    if (isSvg || !(img.naturalWidth)) {
      const w0 = img.naturalWidth || 1024, h0 = img.naturalHeight || 1024, s = 2048 / Math.max(w0, h0);
      const c = document.createElement('canvas'); c.width = Math.round(w0 * s); c.height = Math.round(h0 * s);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      return ST.trim(c);
    }
    return ST.toCanvas(img, 2048);
  })());
  return srcCache.get(src);
}
async function decalCanvas(p) {
  if (p.type === 'text') { await ST.ensureFont(p.text); return ST.renderText(p.text).canvas; }
  if (p.type === 'shape') return ST.renderShape(p.shape).canvas;
  const src = await sourceCanvas(p.image.src);
  return p.image.cut.mode !== 'off' ? ST.trim(ST.cutout(src, p.image.cut)) : src;
}
function makeTex(canvas) {
  const t = new THREE.CanvasTexture(canvas);
  t.flipY = false; t.colorSpace = THREE.NoColorSpace; t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true;
  return t;
}
function decalSize(p, aspect) { const h = p.h; return { w: h * aspect * (p.type === 'shape' ? 1 : p.sx), h }; }
function clipFilter(p, mirrored) {
  if (!p.clip) return null;
  const id = mirrored ? p.clip.idM : p.clip.id;
  if (id == null || id < 0) return mirrored ? false : null;
  return p.clip.kind === 'part' ? { part: id } : { island: id };
}
function decalFrames(p, aspect) {
  const { w, h } = decalSize(p, aspect);
  const c = V3(p.c), n = V3(p.n).normalize();
  let up = V3(p.up).addScaledVector(n, -V3(p.up).dot(n));
  if (up.lengthSq() < 1e-6) { up = new THREE.Vector3(0, 0, 1); up.addScaledVector(n, -up.dot(n)); }
  if (up.lengthSq() < 1e-6) up = new THREE.Vector3(0, 1, 0);
  up.normalize();
  const r = new THREE.Vector3().crossVectors(n, up).normalize();     // car space is mirrored: right = n x up reads correctly
  const a = p.rot * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
  const r2 = r.clone().multiplyScalar(ca).addScaledVector(up, -sa);
  const u2 = r.clone().multiplyScalar(sa).addScaledVector(up, ca);
  if (p.flipX) r2.negate();
  if (p.flipY) u2.negate();
  const depth = p.depth || clamp(Math.max(w, h) * 0.35, 0.1, 1.2);
  return withMirror(p, { c, r: r2, u: u2, n, w, h, depth });
}
/** 'readable' keeps text and logos the right way round on the other side; 'exact' is a true reflection
 *  (arrows and swooshes point forward on both sides). Shapes and paths default to exact. */
const mirrorModeOf = p => p.mirrorMode || (p.type === 'shape' || p.type === 'path' ? 'exact' : 'readable');
function withMirror(p, f0) {
  const frames = [{ ...f0, filter: clipFilter(p, false) }];
  if (p.mirror) {
    const filter = clipFilter(p, true);
    const r = mirrorModeOf(p) === 'readable' ? new THREE.Vector3(f0.r.x, -f0.r.y, -f0.r.z) : M(f0.r);
    if (filter !== false) frames.push({ c: M(f0.c), r, u: M(f0.u), n: M(f0.n), w: f0.w, h: f0.h, depth: f0.depth, filter });
  }
  return frames;
}
async function refreshDecal(L, regen = false) {
  const p = L.params, d = L.decal;
  if (regen || !d.tex || p.type === 'path') {
    const ver = d.ver = (d.ver || 0) + 1;
    let canvas;
    try {
      if (p.type === 'path') ({ canvas, frame: d.base } = pathCanvas(p));
      else canvas = await decalCanvas(p);
    } catch (e) { toast(e.message, 'err'); return; }
    if (d.ver !== ver) return;                                        // a newer edit already replaced this one
    d.tex?.dispose();
    d.tex = makeTex(canvas); d.aspect = canvas.width / canvas.height; d.alpha = ST.alphaMap(canvas); d.size = [canvas.width, canvas.height];
  }
  d.tint = p.type === 'image' && p.image.tint ? p.image.tintColor : null;
  d.frames = p.type === 'path' ? withMirror(p, d.base) : decalFrames(p, d.aspect || 1);
  markDirty();
}
function updateClip(p) {
  if (!p.clip) return;
  const a = p.type === 'path' ? p.path.contours[0]?.pts[0] : null;
  const c = V3(a ? a.p : p.c), n = V3(a ? a.n : p.n);
  const h = pickObject(c, n), hm = pickObject(M(c), M(n));
  const id = h => !h ? -1 : p.clip.kind === 'part' ? h.part : h.island;
  p.clip.id = id(h); p.clip.idM = id(hm);
  if (p.clip.idM === p.clip.id) p.clip.idM = -1;                      // panel crosses the centre line: draw it once
}
const DEFAULT_H = { text: 0.22, shape: 0.3, image: 0.3 };
function createDecal(type, hit, extra = {}) {
  const p = { type, c: hit.p.toArray(), n: hit.n.toArray(), up: camUpObject().toArray(), h: DEFAULT_H[type], sx: 1, rot: 0,
              flipX: false, flipY: false, mirror: S.symmetry, clip: null, depth: 0, ...extra };
  if (type === 'text') p.text = structuredClone(S.text);
  if (type === 'shape') p.shape = { ...structuredClone(S.shape), color: S.shape.color };
  if (type === 'image') p.image = { src: S.image.current.src, name: S.image.current.name, cut: structuredClone(S.image.cut), tint: S.image.tint, tintColor: S.image.tintColor };
  const name = type === 'text' ? `Text: ${p.text.text.split('\n')[0].slice(0, 18)}` : type === 'shape' ? (p.shape.shape === 'custom' ? p.shape.customName || 'Custom shape' : ST.SHAPES[p.shape.shape].name) : p.image.name || 'Image';
  let L;
  const e = layersChange(() => { L = engine.addDecalLayer(uniqueName(name), indexAbove()); L.params = p; engine.active = L; });
  pushHistory(e);
  refreshDecal(L, true);
  baseSelected = false;
  renderLayers(); renderOptions();
  return L;
}
function pickDecal(hit, onlyType) {
  for (let i = engine.layers.length - 1; i >= 0; i--) {
    const L = engine.layers[i];
    if (L.kind !== 'decal' || !L.visible || !L.decal.tex) continue;
    if (onlyType && L.params.type !== onlyType) continue;
    for (let k = 0; k < L.decal.frames.length; k++) {
      const f = L.decal.frames[k], rel = hit.p.clone().sub(f.c);
      if (Math.abs(rel.dot(f.n)) > f.depth) continue;
      const a = rel.dot(f.r) / f.w + 0.5, b = 0.5 - rel.dot(f.u) / f.h;
      if (a < 0 || a > 1 || b < 0 || b > 1) continue;
      if (L !== active() && L.decal.alpha.at(a, b) < 24) continue;
      return { layer: L, mirror: k === 1 };
    }
  }
  return null;
}
function setDecalWH(L, w, h) {
  const p = L.params, A = L.decal.aspect || 1;
  w = Math.max(0.01, w); h = Math.max(0.01, h);
  p.h = h;
  if (p.type === 'shape') { p.shape.aspect = clamp(w / h, 0.05, 20); return true; }     // shapes re-render, so outlines stay even
  p.sx = clamp(w / (h * A), 0.05, 20); return false;
}

// ================================================================================================
// pen tool: editable Bezier paths on the body (open = a curved line, closed = a filled shape)
// ================================================================================================
// A path layer keeps its points in car space: {p, n, i, o} = anchor, surface normal, in / out handles.
// It is drawn into a canvas in its projection plane (normal pn) and projected onto the body like any decal.
const pen = { drawing: false, sel: null };                              // sel = [contour, point]
const isPath = L => L?.kind === 'decal' && L.params?.type === 'path';
const activePath = () => isPath(active()) ? active() : null;
const VV = a => a ? V3(a) : null;
function pathBasis(p) {
  const n = V3(p.pn).normalize();
  let up = V3(p.up); up.addScaledVector(n, -up.dot(n));
  if (up.lengthSq() < 1e-6) { up = new THREE.Vector3(0, 0, 1); up.addScaledVector(n, -up.dot(n)); }
  if (up.lengthSq() < 1e-6) up = new THREE.Vector3(0, 1, 0);
  up.normalize();
  return { n, up, r: new THREE.Vector3().crossVectors(n, up).normalize() };
}
function pathPoints(p) { return p.path.contours.flatMap(c => c.pts); }
function pathCentroid(p) { const all = pathPoints(p); return all.reduce((a, q) => a.add(V3(q.p)), new THREE.Vector3()).divideScalar(Math.max(1, all.length)); }
function pathCanvas(p) {
  const P = p.path, { n, up, r } = pathBasis(p), o = pathCentroid(p);
  const to2 = a => { const d = V3(a).sub(o); return [d.dot(r), d.dot(up)]; };
  const c2 = P.contours.map(c => ({ closed: c.closed, pts: c.pts.map(q => ({ p: to2(q.p), i: q.i && to2(q.i), o: q.o && to2(q.o) })) }));
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const c of c2) for (const q of c.pts) for (const v of [q.p, q.i, q.o]) if (v) { x0 = Math.min(x0, v[0]); x1 = Math.max(x1, v[0]); y0 = Math.min(y0, v[1]); y1 = Math.max(y1, v[1]); }
  if (!isFinite(x0)) { x0 = y0 = 0; x1 = y1 = 0; }
  const pad = (P.stroke ? P.width / 2 : 0) + 0.01;
  x0 -= pad; y0 -= pad; x1 += pad; y1 += pad;
  const s = Math.min(900, 4096 / Math.max(x1 - x0, y1 - y0));             // pixels per metre
  const cv = document.createElement('canvas');
  cv.width = Math.max(8, Math.ceil((x1 - x0) * s)); cv.height = Math.max(8, Math.ceil((y1 - y0) * s));
  const g = cv.getContext('2d'); g.lineJoin = g.lineCap = 'round';
  g.beginPath(); ST.traceContours(g, c2, ([x, y]) => [(x - x0) * s, (y1 - y) * s]);
  if (P.fill && c2.some(c => c.closed && c.pts.length > 2)) { g.fillStyle = P.fillColor; g.fill(P.rule || 'nonzero'); }
  if (P.stroke) { g.lineWidth = Math.max(1, P.width * s); g.strokeStyle = P.strokeColor; g.stroke(); }
  const w = cv.width / s, h = cv.height / s;
  const c = o.clone().addScaledVector(r, x0 + w / 2).addScaledVector(up, y1 - h / 2);
  let dev = 0; for (const q of pathPoints(p)) dev = Math.max(dev, Math.abs(V3(q.p).sub(c).dot(n)));
  const depth = p.depth || Math.max(0.08, dev * 1.25 + 0.04 + (P.stroke ? P.width : 0));
  return { canvas: cv, frame: { c, r, u: up, n, w, h, depth } };
}
function bez(a, b, t) {                                                  // point on the curve from anchor a to anchor b
  const P0 = V3(a.p), P1 = VV(a.o) || P0.clone(), P3 = V3(b.p), P2 = VV(b.i) || P3.clone(), u = 1 - t;
  return P0.multiplyScalar(u * u * u).addScaledVector(P1, 3 * u * u * t).addScaledVector(P2, 3 * u * t * t).addScaledVector(P3, t * t * t);
}
function segments(c) {
  const out = [];
  for (let k = 1; k < c.pts.length; k++) out.push([k - 1, k]);
  if (c.closed && c.pts.length > 2) out.push([c.pts.length - 1, 0]);
  return out;
}
function splitSegment(c, ia, ib, t) {                                    // de Casteljau: same curve, one more point
  const a = c.pts[ia], b = c.pts[ib];
  const P0 = V3(a.p), P1 = VV(a.o) || P0.clone(), P3 = V3(b.p), P2 = VV(b.i) || P3.clone(), L = (x, y) => x.clone().lerp(y, t);
  const P01 = L(P0, P1), P12 = L(P1, P2), P23 = L(P2, P3), P012 = L(P01, P12), P123 = L(P12, P23), Q = L(P012, P123);
  const curved = !!(a.o || b.i);
  const np = { p: Q.toArray(), n: V3(a.n).lerp(V3(b.n), t).normalize().toArray(), i: curved ? P012.toArray() : null, o: curved ? P123.toArray() : null };
  if (curved) { a.o = P01.toArray(); b.i = P23.toArray(); }
  const at = ib === 0 ? c.pts.length : ib;
  c.pts.splice(at, 0, np);
  return at;
}
function nearestSegment(L, x, y) {
  const r = view.getBoundingClientRect(); x -= r.left; y -= r.top;
  let best = null;
  L.params.path.contours.forEach((c, ci) => segments(c).forEach(([ia, ib]) => {
    for (let k = 1; k < 30; k++) {
      const t = k / 30, s = toScreen(bez(c.pts[ia], c.pts[ib], t)), d = Math.hypot(s.x - x, s.y - y);
      if (!s.behind && (!best || d < best.d)) best = { d, ci, ia, ib, t };
    }
  }));
  return best;
}
function rayPlanePoint(x, y, pObj, nObj) {                               // pointer onto the plane touching the body at pObj
  const r = renderer.domElement.getBoundingClientRect();
  ndc.set((x - r.left) / r.width * 2 - 1, -(y - r.top) / r.height * 2 + 1);
  camera.updateMatrixWorld(); raycaster.setFromCamera(ndc, camera);
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(toWorldDir(nObj).normalize(), car.group.localToWorld(pObj.clone()));
  const out = raycaster.ray.intersectPlane(plane, new THREE.Vector3());
  if (!out || Math.abs(raycaster.ray.direction.dot(plane.normal)) < 0.1) return planePoint(x, y, pObj);
  return car.group.worldToLocal(out);
}
function refitNormal(p) {                                                // project along the average surface normal of the points
  const s = new THREE.Vector3(); for (const q of pathPoints(p)) s.add(V3(q.n));
  if (s.lengthSq() > 1e-6) p.pn = s.normalize().toArray();
}
function transformPath(p, f) { for (const q of pathPoints(p)) for (const w of ['p', 'i', 'o']) if (q[w]) q[w] = f(V3(q[w])).toArray(); }
function beginEditFor(L) { if (pendingEdit?.layer !== L) { endEdit(); pendingEdit = { layer: L, before: snap(L) }; } }
function createPath(hit) {
  const p = { type: 'path', pn: hit.n.toArray(), up: camUpObject().toArray(), mirror: S.symmetry, mirrorMode: 'exact', clip: null, depth: 0,
    path: { contours: [{ closed: false, pts: [{ p: hit.p.toArray(), n: hit.n.toArray(), i: null, o: null }] }],
            stroke: true, strokeColor: S.color, width: S.pen.width, fill: false, fillColor: S.color, rule: 'nonzero' } };
  let L;
  pushHistory(layersChange(() => { L = engine.addDecalLayer(uniqueName('Path'), indexAbove()); L.params = p; engine.active = L; }));
  refreshDecal(L, true); baseSelected = false;
  renderLayers(); renderOptions();
  return L;
}
function addPathPoint(L, hit, e) {
  beginEditFor(L);
  const P = L.params.path, c = P.contours.at(-1);
  c.pts.push({ p: hit.p.toArray(), n: hit.n.toArray(), i: null, o: null });
  refitNormal(L.params);
  pen.sel = [P.contours.length - 1, c.pts.length - 1];
  drag = { kind: 'pen-new', layer: L, ci: pen.sel[0], pi: pen.sel[1], x0: e.clientX, y0: e.clientY };
  queueRegen(L);
}
function closeContour(P, c) {
  c.closed = true;
  if (!P.closedOnce) { P.fill = true; P.stroke = false; P.closedOnce = true; }   // a closed path becomes a filled shape
}
function finishPath() {
  pen.drawing = false;
  const L = activePath();
  endEdit();
  if (L) {
    const keep = L.params.path.contours.filter(c => c.pts.length >= 2);
    if (!keep.length) { deleteLayer(L); pen.sel = null; return; }
    if (keep.length !== L.params.path.contours.length) editLayer(L, x => { x.params.path.contours = keep; }, true, true);
  }
  pen.sel = null; renderOptions();
}
function toggleCorner(c, pi) {
  const q = c.pts[pi], n = c.pts.length;
  if (q.i || q.o) { q.i = q.o = null; return; }
  if (n < 2) return;
  const P = V3(q.p), prev = V3(c.pts[(pi - 1 + n) % n].p), next = V3(c.pts[(pi + 1) % n].p);
  let dir = next.clone().sub(prev).multiplyScalar(0.25);
  if (!c.closed && pi === 0) dir = next.clone().sub(P).multiplyScalar(0.35);
  if (!c.closed && pi === n - 1) dir = P.clone().sub(prev).multiplyScalar(0.35);
  q.o = P.clone().add(dir).toArray(); q.i = P.clone().sub(dir).toArray();
}
function deletePathPoint(L) {
  if (!pen.sel) return;
  const [ci, pi] = pen.sel;
  editLayer(L, x => {
    const cs = x.params.path.contours, c = cs[ci]; if (!c) return;
    c.pts.splice(pi, 1);
    if (c.closed && c.pts.length < 3) c.closed = false;
    if (c.pts.length < 2) cs.splice(ci, 1);
  }, true, true);
  pen.sel = null;
  if (!L.params.path.contours.length) deleteLayer(L);
  renderOptions();
}
/** Pointer down with the pen tool. Returns true when the pen used the click. */
function penDown(e) {
  const ds = e.target?.dataset || {}, L = activePath();
  if (L && (ds.pa || ds.ph)) {
    const P = L.params.path;
    if (ds.pa) {
      const [ci, pi] = ds.pa.split(':').map(Number), c = P.contours[ci];
      const drawingThis = pen.drawing && ci === P.contours.length - 1;
      if (drawingThis && pi === 0 && c.pts.length >= 3) { editLayer(L, () => closeContour(P, c), true, true); finishPath(); return true; }
      if (drawingThis && pi === c.pts.length - 1 && c.pts.length >= 2) { finishPath(); return true; }
      if (e.altKey) { editLayer(L, () => toggleCorner(c, pi), true, true); pen.sel = [ci, pi]; return true; }
      pen.sel = [ci, pi];
      const sp = toScreen(V3(c.pts[pi].p)), r = view.getBoundingClientRect();
      drag = { kind: 'pen-anchor', layer: L, ci, pi, off: { x: sp.x + r.left - e.clientX, y: sp.y + r.top - e.clientY } };
      beginEditFor(L); renderOptions(); return true;
    }
    const [ci, pi, w] = ds.ph.split(':');
    drag = { kind: 'pen-handle', layer: L, ci: +ci, pi: +pi, w, alt: e.altKey };
    beginEditFor(L); return true;
  }
  const hit = pick(e.clientX, e.clientY);
  if (!hit) return false;
  if (L && pen.drawing) { if (hit.isPaint) addPathPoint(L, hit, e); return true; }
  if (L) {
    const sg = nearestSegment(L, e.clientX, e.clientY);
    if (sg && sg.d < 7) { editLayer(L, x => { pen.sel = [sg.ci, splitSegment(x.params.path.contours[sg.ci], sg.ia, sg.ib, sg.t)]; }, true, true); renderOptions(); return true; }
  }
  const other = pickDecal(hit, 'path');
  if (other && other.layer !== L) { setActive(other.layer); pen.sel = null; return true; }
  if (!hit.isPaint) return false;
  const NL = createPath(hit);
  pen.drawing = true; pen.sel = [0, 0];
  drag = { kind: 'pen-new', layer: NL, ci: 0, pi: 0, x0: e.clientX, y0: e.clientY };
  return true;
}
function penMove(e) {
  const d = drag, q = d.layer.params.path.contours[d.ci]?.pts[d.pi];
  if (!q) return;
  if (d.kind === 'pen-new') {                                            // dragging out a curve from a new point
    if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 4) return;
    const P = V3(q.p), h = rayPlanePoint(e.clientX, e.clientY, P, V3(q.n));
    q.o = h.toArray(); q.i = P.clone().multiplyScalar(2).sub(h).toArray();
  } else if (d.kind === 'pen-anchor') {
    const hit = pick(e.clientX + d.off.x, e.clientY + d.off.y);
    if (!hit) return;
    const delta = hit.p.clone().sub(V3(q.p));
    q.p = hit.p.toArray(); q.n = hit.n.toArray();
    for (const w of ['i', 'o']) if (q[w]) q[w] = V3(q[w]).add(delta).toArray();
  } else {
    const P = V3(q.p), h = rayPlanePoint(e.clientX, e.clientY, P, V3(q.n)), other = d.w === 'i' ? 'o' : 'i';
    q[d.w] = h.toArray();
    if (!d.alt && !e.altKey && q[other]) {                               // smooth point: keep the opposite handle in line
      const len = V3(q[other]).distanceTo(P), dir = P.clone().sub(h);
      if (dir.lengthSq() > 1e-10) q[other] = P.clone().addScaledVector(dir.normalize(), len).toArray();
    }
  }
  queueRegen(d.layer);
}
let penG = null;                                                         // created with the other SVG handles
const outlineCache = new WeakMap();
/** Where the path's outline lands on the body (projected along its projection normal, like the paint). */
function surfaceOutline(L) {
  const key = JSON.stringify(L.params.path.contours) + L.params.pn;
  const hit = outlineCache.get(L);
  if (hit?.key === key) return hit.pts;
  const n = V3(L.params.pn).normalize();
  const pts = L.params.path.contours.map(c => {
    if (!c.pts.length) return [];
    const out = [onBodyAlong(V3(c.pts[0].p), n)];
    for (const [ia, ib] of segments(c)) for (let k = 1; k <= 16; k++) out.push(onBodyAlong(bez(c.pts[ia], c.pts[ib], k / 16), n));
    return out;
  });
  const anchors = L.params.path.contours.map(c => c.pts.map(q => onBodyAlong(V3(q.p), n)));
  outlineCache.set(L, { key, pts: { lines: pts, anchors } });
  return { lines: pts, anchors };
}
function onBodyAlong(v, n) {                                             // ray along -n through v onto the paint
  if (!car) return v;
  const o = car.group.localToWorld(v.clone().addScaledVector(n, 0.3));
  raycaster.set(o, new THREE.Vector3(n.x, -n.y, -n.z).normalize());     // world direction of -n
  raycaster.far = 0.6;
  const h = hitInfo(raycaster.intersectObjects(car.meshes, false)[0]);
  raycaster.far = Infinity;
  return h ? h.p : v;
}
const visCache = { key: '', map: new Map() };
/** Is this car-space point in view (not hidden behind the body)? Cached until the camera or the path changes. */
function seen(p) {
  const key = camera.matrixWorld.elements.join(',');
  if (key !== visCache.key) { visCache.key = key; visCache.map.clear(); }
  const k = p.x.toFixed(4) + ',' + p.y.toFixed(4) + ',' + p.z.toFixed(4);
  if (visCache.map.has(k)) return visCache.map.get(k);
  const w = car.group.localToWorld(p.clone()), d = w.distanceTo(camera.position);
  raycaster.set(camera.position, w.clone().sub(camera.position).normalize()); raycaster.far = d - 0.004;
  const vis = !raycaster.intersectObjects(car.meshes, false).length;
  raycaster.far = Infinity;
  visCache.map.set(k, vis);
  return vis;
}
function drawPen() {
  const L = activePath();
  if (S.tool !== 'pen' || !L) { if (penG.firstChild) { penG.innerHTML = ''; penG.last = ''; } return; }
  const P = L.params.path, f = v => v.toFixed(1);
  let out = '';
  const scr = a => toScreen(V3(a)), body = surfaceOutline(L);
  for (const line of body.lines) {                                      // visible parts solid, hidden parts faint
    if (line.length < 2) continue;
    let run = [], runVis = null;
    const flush = () => { if (run.length > 1) out += `<polyline points="${run.map(q => f(q.x) + ',' + f(q.y)).join(' ')}" fill="none" stroke="#ff6a1a" stroke-width="1.5"${runVis ? '' : ' stroke-opacity="0.3" stroke-dasharray="3 4"'}/>`; };
    for (const v of line) {
      const vis = seen(v), q = toScreen(v);
      if (runVis !== null && vis !== runVis) { run.push(q); flush(); run = [q]; } else run.push(q);
      runVis = vis;
    }
    flush();
  }
  const anchorAt = (ci, pi) => body.anchors[ci]?.[pi] ? toScreen(body.anchors[ci][pi]) : scr(P.contours[ci].pts[pi].p);
  if (pen.drawing && hover && !drag) {
    const ci = P.contours.length - 1, last = P.contours[ci]?.pts.length - 1;
    if (last >= 0) { const a = anchorAt(ci, last), r = view.getBoundingClientRect();
      out += `<line x1="${f(a.x)}" y1="${f(a.y)}" x2="${f(hover.x - r.left)}" y2="${f(hover.y - r.top)}" stroke="#fff" stroke-width="1.2" stroke-dasharray="4 4"/>`; }
  }
  const showH = new Set();
  if (pen.sel) { const [ci, pi] = pen.sel, n = P.contours[ci]?.pts.length || 0; if (n) [pi, (pi + 1) % n, (pi - 1 + n) % n].forEach(k => showH.add(ci + ':' + k)); }
  let anchors = '';
  P.contours.forEach((c, ci) => c.pts.forEach((q, pi) => {
    const a = anchorAt(ci, pi);
    if (a.behind) return;
    if (showH.has(ci + ':' + pi)) for (const w of ['i', 'o']) if (q[w]) {
      const hh = scr(q[w]);
      out += `<line x1="${f(a.x)}" y1="${f(a.y)}" x2="${f(hh.x)}" y2="${f(hh.y)}" stroke="#9fd3ff" stroke-width="1"/>` +
             `<circle class="h" data-ph="${ci}:${pi}:${w}" cx="${f(hh.x)}" cy="${f(hh.y)}" r="4.5" fill="#9fd3ff" stroke="#111"/>`;
    }
    const on = pen.sel && pen.sel[0] === ci && pen.sel[1] === pi;
    const hidden = body.anchors[ci]?.[pi] && !seen(body.anchors[ci][pi]);
    anchors += `<rect class="h" data-pa="${ci}:${pi}" x="${f(a.x - 4.5)}" y="${f(a.y - 4.5)}" width="9" height="9" fill="${on ? '#ff6a1a' : '#fff'}" stroke="#111" stroke-width="1.2"${hidden ? ' opacity="0.35"' : ''}/>`;
  }));
  const html = out + anchors;
  if (html !== penG.last) { penG.innerHTML = html; penG.last = html; }   // only touch the DOM when something moved
}
/** Turn a shape into a path with the same outline, so its points and curves can be edited. */
function shapeToPath(L) {
  const p = L.params, f = L.decal.frames[0], [cw, ch] = L.decal.size || [1024, 1024];
  if (!f) return;
  const pad = p.shape.outline * Math.min(cw, ch) * 0.25 + 2;
  const { contours, evenodd } = ST.shapeContours(p.shape);
  const to3 = ([x, y]) => { const xn = (pad + x * (cw - 2 * pad)) / cw, yn = (pad + y * (ch - 2 * pad)) / ch;
    return f.c.clone().addScaledVector(f.r, (xn - 0.5) * f.w).addScaledVector(f.u, (0.5 - yn) * f.h).toArray(); };
  const n = f.n.toArray();
  const path = { contours: contours.map(c => ({ closed: c.closed, pts: c.pts.map(q => ({ p: to3(q.p), n, i: q.i && to3(q.i), o: q.o && to3(q.o) })) })),
    fill: true, fillColor: p.shape.color, stroke: p.shape.outline > 0, strokeColor: p.shape.outlineColor,
    width: Math.max(0.002, p.shape.outline * Math.min(cw, ch) * 0.5 / cw * f.w), rule: evenodd ? 'evenodd' : 'nonzero', closedOnce: true };
  editLayer(L, x => {
    x.params = { type: 'path', pn: f.n.toArray(), up: f.u.toArray(), mirror: p.mirror, mirrorMode: mirrorModeOf(p), clip: p.clip, depth: p.depth, path };
    x.name = uniqueName('Path: ' + x.name);
  }, true, true);
  pen.sel = null; pen.drawing = false;
  setTool('pen', { keepSelection: true }); renderLayers();
  toast('Now a path: drag the points and handles, click the outline to add points', 'ok', 4000);
}

// ---- selection handles (SVG overlay) -----------------------------------------------------------
const svg = $('#handles');
const NS = 'http://www.w3.org/2000/svg';
const svgEl = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
const H = {
  poly: svgEl('polygon', { fill: 'none', stroke: '#ff6a1a', 'stroke-width': 1.5, 'stroke-dasharray': '6 4' }),
  stem: svgEl('line', { stroke: '#ff6a1a', 'stroke-width': 1.5 }),
  grad: svgEl('line', { stroke: '#fff', 'stroke-width': 2, 'stroke-dasharray': '5 4' }),
  handles: [],
};
penG = svgEl('g', {});
svg.append(H.poly, H.stem, H.grad, penG);
for (const id of ['c0', 'c1', 'c2', 'c3', 'e0', 'e1', 'e2', 'e3', 'rot']) {
  const e = id.startsWith('c') || id === 'rot' ? svgEl('circle', { r: id === 'rot' ? 7 : 6 }) : svgEl('rect', { width: 10, height: 10 });
  e.setAttribute('class', 'h'); e.dataset.h = id;
  e.setAttribute('fill', id === 'rot' ? '#ff6a1a' : '#fff'); e.setAttribute('stroke', '#111'); e.setAttribute('stroke-width', 1.2);
  e.style.cursor = id === 'rot' ? 'grab' : id.startsWith('c') ? 'nwse-resize' : 'ew-resize';
  svg.append(e); H.handles.push(e);
}
const showHandles = () => ['select', 'shape', 'text', 'image'].includes(S.tool) && active()?.kind === 'decal' && !isPath(active());
let handleGeom = null;
function drawHandles() {
  const L = active(), f = L?.decal?.frames?.[0];
  const vis = showHandles() && f && !toScreen(f.c).behind;
  for (const e of [H.poly, H.stem, ...H.handles]) e.style.display = vis ? '' : 'none';
  handleGeom = null;
  if (!vis) return;
  const P = (sx, sy) => toScreen(f.c.clone().addScaledVector(f.r, sx * f.w / 2).addScaledVector(f.u, sy * f.h / 2));
  const cs = [P(-1, 1), P(1, 1), P(1, -1), P(-1, -1)];
  const es = [P(0, 1), P(1, 0), P(0, -1), P(-1, 0)];
  const c = toScreen(f.c);
  H.poly.setAttribute('points', cs.map(p => `${p.x},${p.y}`).join(' '));
  cs.forEach((p, i) => { H.handles[i].setAttribute('cx', p.x); H.handles[i].setAttribute('cy', p.y); });
  es.forEach((p, i) => { H.handles[4 + i].setAttribute('x', p.x - 5); H.handles[4 + i].setAttribute('y', p.y - 5); });
  const dx = es[0].x - c.x, dy = es[0].y - c.y, len = Math.hypot(dx, dy) || 1;
  const k = { x: es[0].x + dx / len * 26, y: es[0].y + dy / len * 26 };
  H.handles[8].setAttribute('cx', k.x); H.handles[8].setAttribute('cy', k.y);
  H.stem.setAttribute('x1', es[0].x); H.stem.setAttribute('y1', es[0].y); H.stem.setAttribute('x2', k.x); H.stem.setAttribute('y2', k.y);
  const ax = { x: es[1].x - c.x, y: es[1].y - c.y }, ay = { x: es[0].x - c.x, y: es[0].y - c.y };
  handleGeom = { c, ax, ay, det: ax.x * ay.y - ax.y * ay.x };
}

// ================================================================================================
// tools
// ================================================================================================
const ICONS = {
  select: '<path d="M5 3l12 8-5 1.5L9.5 18z"/>',
  pen: '<path d="M12 3l5 9-5 9-5-9z"/><circle cx="12" cy="12" r="1.6"/><path d="M12 3v7"/>',
  brush: '<path d="M14 4l6 6-8.5 8.5c-1 1-2.5 1-3.5 0l-2.5-2.5c-1-1-1-2.5 0-3.5z"/><path d="M5.5 15.5L3 21l5.5-2.5"/>',
  eraser: '<path d="M8 20h12"/><path d="M4.5 15.5l9-9a2 2 0 012.8 0l3.2 3.2a2 2 0 010 2.8L13 19H8.5z"/>',
  fill: '<path d="M5 11l7-7 8 8-7 7z"/><path d="M20 17c0 1.5 1 2.5 1 3.5a1 1 0 01-2 0c0-1 1-2 1-3.5z"/>',
  line: '<path d="M4 20L20 4"/><circle cx="4" cy="20" r="1.5"/><circle cx="20" cy="4" r="1.5"/>',
  gradient: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 21L21 7M3 15L15 3M11 21L21 11"/>',
  pattern: '<circle cx="7" cy="7" r="2"/><circle cx="17" cy="7" r="2"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/><circle cx="12" cy="12" r="2"/>',
  shape: '<rect x="3" y="11" width="9" height="9"/><circle cx="16" cy="8" r="5"/>',
  text: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 17l-5-5-9 8"/>',
  eyedropper: '<path d="M19 3l2 2-4 4 1 1-2 2-6-6 2-2 1 1z"/><path d="M11 9l-7 7v4h4l7-7"/>',
};
const TOOLS = [
  ['select', 'Select & move decals (V)', 'v'], ['brush', 'Brush (B)', 'b'], ['eraser', 'Eraser (E)', 'e'], ['fill', 'Paint bucket (F)', 'f'],
  ['line', 'Straight line (L)', 'l'], ['pen', 'Pen: curved lines and editable shapes (P)', 'p'], ['gradient', 'Gradient (G)', 'g'], ['pattern', 'Patterns & textures (K)', 'k'], null,
  ['shape', 'Shapes (U)', 'u'], ['text', 'Text (T)', 't'], ['image', 'Images & logos (M)', 'm'], null, ['eyedropper', 'Pick colour (I, or Alt+click)', 'i'],
];
const HINTS = {
  select: 'Click a text / shape / image to select it · drag to move · handles: resize, stretch, rotate · Delete removes it',
  brush: 'Drag on the car to paint · Shift+wheel or [ ] size · Alt+click picks a colour · right-drag orbits, middle-drag pans',
  eraser: 'Drag to erase on the current layer · Shift+wheel or [ ] size',
  fill: 'Click a panel to fill it · choose Panel, Part or Whole car on the left',
  line: 'Drag to draw a line · hold Shift to snap the angle',
  gradient: 'Drag across the car: the first colour starts where you press, the last ends where you let go',
  pattern: 'Adjust the pattern on the left, then Apply (Enter) · with Panels / Parts click as many as you want · drag on the car to fade it out',
  pen: 'Click to add points · click and drag for a curve · click the first point to close a shape · Enter finishes a line · Alt+click a point: corner / curve',
  shape: 'Click the car to place a shape (drag to size it) · click a shape to move it · Shift+wheel size · Alt+wheel rotate',
  text: 'Click the car to place text · type on the left · Shift+wheel size · Alt+wheel rotate',
  image: 'Pick a logo or upload an image, then click the car to place it',
  eyedropper: 'Click the car to pick its paint colour (gloss and reflections are ignored)',
};
function buildToolbar() {
  const bar = $('#tools'); bar.innerHTML = '';
  for (const t of TOOLS) {
    if (!t) { bar.append(el('div', { class: 'gap' })); continue; }
    const b = el('button', { title: t[1], class: S.tool === t[0] ? 'on' : '', onclick: () => setTool(t[0]) });
    b.innerHTML = `<svg viewBox="0 0 24 24">${ICONS[t[0]]}</svg>`;
    b.dataset.tool = t[0];
    bar.append(b);
  }
}
function setTool(t, { keepSelection = false } = {}) {
  if (t !== 'pen' && pen.drawing) finishPath();
  endEdit();
  if (t !== 'pattern') cancelPattern();
  if (t !== 'pen') pen.sel = null;
  S.tool = t; saveSettings();
  document.querySelectorAll('#tools button').forEach(b => b.classList.toggle('on', b.dataset.tool === t));
  const L = active();
  if (!keepSelection && L?.kind === 'decal' && ['shape', 'text', 'image'].includes(t) && L.params.type !== t) { /* keep the layer selected, handles hide */ }
  $('#hint').textContent = HINTS[t] || '';
  renderOptions();
  if (t === 'pattern') previewPattern();
}

// ---- strokes: brush, eraser, line ----------------------------------------------------------------
let drag = null;
function stepPx(radius, hit) {
  const dist = hit ? hit.distance : camera.position.distanceTo(controls.target);
  const wpp = 2 * dist * Math.tan(camera.fov * Math.PI / 360) / Math.max(1, view.clientHeight);
  return Math.max(1, radius * 0.22 / wpp);
}
function addDab(list, hit, r, protect) {
  list.push({ p: hit.p, n: hit.n, r, island: protect ? hit.island : -1 });
  if (S.symmetry) {
    const pm = M(hit.p), nm = M(hit.n);
    const isl = protect ? (pickObject(pm, nm)?.island ?? -1) : -1;
    list.push({ p: pm, n: nm, r, island: isl });
  }
}
function beginStroke(e) {
  if (S.tool === 'eraser' && active()?.kind !== 'paint') return toast(active() ? 'The eraser works on paint layers. Use "Convert to paint layer" first.' : 'Select a paint layer to erase', '', 4000);
  const L = ensurePaintLayer();
  if (S.tool !== 'eraser') warnLockedEmpty(L);
  const o = S[S.tool];
  engine.active = L; engine.clearOverlay(); engine.setOverlayMode(S.tool === 'eraser' ? 1 : 0, o.opacity);
  drag = { kind: 'stroke', layer: L, o, last: null, color: S.color };
  strokeTo(e);
}
function strokeTo(e) {
  const d = drag, o = d.o, pts = [];
  const evs = e.getCoalescedEvents?.().length ? e.getCoalescedEvents() : [e];
  for (const ev of evs) {
    const x = ev.clientX, y = ev.clientY;
    if (!d.last) { pts.push([x, y, ev.pressure]); d.last = { x, y, hit: null }; continue; }
    const dx = x - d.last.x, dy = y - d.last.y, dist = Math.hypot(dx, dy);
    const n = Math.ceil(dist / stepPx(o.size, d.last.hit));
    for (let i = 1; i <= n; i++) pts.push([d.last.x + dx * i / n, d.last.y + dy * i / n, ev.pressure]);
    d.last.x = x; d.last.y = y;
  }
  const dabs = [];
  for (const [x, y, pr] of pts) {
    const hit = pick(x, y);
    if (!hit?.isPaint) continue;
    const r = o.size * (o.pressure && e.pointerType === 'pen' ? 0.15 + 0.85 * (pr || 0.5) : 1);
    addDab(dabs, hit, r, o.protect); d.last.hit = hit;
  }
  if (dabs.length) { engine.dabs(dabs, { hardness: o.hardness, color: d.color, protect: o.protect }); d.drew = true; markDirty(); }
}
function lineTo(e) {
  const d = drag, o = S.line;
  let x = e.clientX, y = e.clientY;
  if (e.shiftKey) {
    const a = Math.round(Math.atan2(y - d.y0, x - d.x0) / (Math.PI / 12)) * Math.PI / 12, len = Math.hypot(x - d.x0, y - d.y0);
    x = d.x0 + Math.cos(a) * len; y = d.y0 + Math.sin(a) * len;
  }
  engine.clearOverlay(); engine.setOverlayMode(0, o.opacity);
  const h0 = pick(d.x0, d.y0), dist = Math.hypot(x - d.x0, y - d.y0), n = Math.max(1, Math.ceil(dist / stepPx(o.size, h0)));
  const dabs = [];
  for (let i = 0; i <= n; i++) { const hit = pick(d.x0 + (x - d.x0) * i / n, d.y0 + (y - d.y0) * i / n); if (hit?.isPaint) addDab(dabs, hit, o.size, o.protect); }
  engine.dabs(dabs, { hardness: o.hardness, color: S.color, protect: o.protect });
  d.drew = dabs.length > 0;
  markDirty();
}
function commitTo(L) {
  const before = reg(engine.commit(L));
  if (before) pushHistory({ t: 'pixels', layer: L, rt: before });
  markDirty(); renderLayers(false);
}

// ---- fill ------------------------------------------------------------------------------------
function texParams(o) {
  const t = TEXTURES[o.with];
  return { type: t.type, spacing: t.spacing * o.scale, size: t.size ?? 0.6, c1: o.c1, c2: o.c2, two: !!t.two, angle: o.angle, proj: 0 };
}
function doFill(hit) {
  const L = ensurePaintLayer(), o = S.fill;
  warnLockedEmpty(L);
  engine.active = L; engine.clearOverlay(); engine.setOverlayMode(0, o.opacity);
  const draw = f => o.with === 'colour' ? engine.fill(S.color, 1, f) : engine.pattern(texParams(o), f);
  draw(filterFor(o.target, hit));
  if (S.symmetry) { const fm = mirroredFilter(o.target, hit); if (fm) draw(fm); }
  commitTo(L);
}

// ---- gradient ------------------------------------------------------------------------------
function planePoint(x, y, aObj) {
  const r = renderer.domElement.getBoundingClientRect();
  ndc.set((x - r.left) / r.width * 2 - 1, -(y - r.top) / r.height * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const aw = car.group.localToWorld(aObj.clone());
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), aw);
  const out = raycaster.ray.intersectPlane(plane, new THREE.Vector3());
  return out ? car.group.worldToLocal(out) : aObj.clone();
}
function beginGradient(e, hit) {
  const o = S.gradient, cur = active();
  let clip = !!(o.clip && cur);                                    // "only where it has paint" means nothing on the car base
  if (clip && cur.kind === 'decal') {                              // a gradient on a shape / text: turn it into paint first
    toast(`"${cur.name}" was converted to a paint layer so the gradient can go on it`, '', 4000);
    rasterizeLayer(cur);
  } else if (clip && !engine.hasPaint(cur)) {
    clip = false;
    toast(`"${cur.name}" is empty, so the gradient goes on normally (not only where it has paint)`, '', 5000);
  }
  const L = ensurePaintLayer();
  if (!clip) warnLockedEmpty(L);
  engine.active = L;
  drag = { kind: 'grad', layer: L, clip, a: hit.p.clone(), x0: e.clientX, y0: e.clientY, filter: filterFor(o.target, hit), filterM: S.symmetry ? mirroredFilter(o.target, hit) : null };
  gradientTo(e);
}
function gradStops() {
  const o = S.gradient;
  if (!(o.stops?.length >= 2)) o.stops = presetStops('Main → second');
  return o.stops;
}
function presetStops(name) {
  if (name === 'Main → second') return [{ pos: 0, color: S.color, alpha: 1 }, { pos: 1, color: S.color2, alpha: 1 }];
  if (name === 'Fade out') return [{ pos: 0, color: S.color, alpha: 1 }, { pos: 1, color: S.color, alpha: 0 }];
  return GRADIENT_PRESETS[name].map(([color, pos]) => ({ pos, color, alpha: 1 }));
}
function gradientTo(e) {
  const d = drag, o = S.gradient;
  const hit = pick(e.clientX, e.clientY);
  const b = hit?.isPaint ? hit.p : planePoint(e.clientX, e.clientY, d.a);
  engine.clearOverlay(); engine.setOverlayMode(d.clip ? 2 : 0, 1);
  const args = { type: o.type, stops: gradStops(), blend: o.blend, repeat: o.repeat };
  engine.gradient({ ...args, a: d.a, b, filter: d.filter });
  if (d.filterM) engine.gradient({ ...args, a: M(d.a), b: M(b), filter: d.filterM });
  markDirty();
  const r = view.getBoundingClientRect();
  Object.entries({ x1: d.x0 - r.left, y1: d.y0 - r.top, x2: e.clientX - r.left, y2: e.clientY - r.top }).forEach(([k, v]) => H.grad.setAttribute(k, v));
  H.grad.style.display = '';
}

// ---- pattern: live preview; whole car, or the panels / parts you click (as many as you like) -------
const pat = { layer: null, sel: new Set(), target: null };
const patName = () => S.pattern.type >= 9 ? PATTERNS[S.pattern.type] : PATTERNS[S.pattern.type] + ' pattern';
const islandsOfPart = pi => { const [a, b] = car.islandRange[pi] || [0, 0]; return Array.from({ length: b - a }, (_, k) => a + k); };
function patTargetLayer() {
  if (S.pattern.into !== 'current') return null;
  if (pat.target && engine.layers.includes(pat.target)) return pat.target;
  const L = active();
  return L?.kind === 'paint' && !L.pending ? (pat.target = L) : null;
}
/** Where the pattern is full (A) and where it has faded away (B), in car space. */
function fadeAxis(o) {
  const b = car.bounds, cy = (b.min.y + b.max.y) / 2, cz = (b.min.z + b.max.z) / 2;   // the car's front is -z
  const presets = { 1: [[0, cy, b.min.z], [0, cy, b.max.z]], 2: [[0, cy, b.max.z], [0, cy, b.min.z]],
                    3: [[0, b.min.y, cz], [0, b.max.y, cz]], 4: [[0, b.max.y, cz], [0, b.min.y, cz]] };
  return o.fadeDir === 5 && o.fadeA && o.fadeB ? [o.fadeA, o.fadeB] : presets[o.fadeDir] || presets[2];
}
function patParams() {
  const o = S.pattern, p = { ...o, fadeType: 'none' };
  if (o.fadeDir) { const [A, B] = fadeAxis(o); Object.assign(p, { fadeType: o.fadeShape || 'linear', fadeA: A, fadeB: B }); }
  return p;
}
function dropPending() {
  if (!pat.layer?.pending) return;
  const i = engine.layers.indexOf(pat.layer);
  if (i >= 0) engine.layers.splice(i, 1);
  if (engine.active === pat.layer) {
    if (pat.fromBase) { engine.active = null; baseSelected = true; }
    else engine.active = engine.layers[i - 1] || engine.layers.at(-1) || null;
  }
  pat.layer = null; gc();
}
function previewPattern() {
  if (!engine || S.tool !== 'pattern') return;
  const o = S.pattern, panels = o.target !== 'layer';
  if (panels && !pat.sel.size) { if (pat.layer) { engine.clearOverlay(); markDirty(); } return; }      // waiting for clicks
  const cur = patTargetLayer();
  let changed = false;
  if (cur) { if (pat.layer !== cur) { dropPending(); pat.layer = cur; changed = true; } }
  else if (!pat.layer || !pat.layer.pending || !engine.layers.includes(pat.layer)) {
    pat.fromBase = baseSelected;                                   // Car base selected: the pattern goes right above the base
    pat.layer = engine.addLayer(uniqueName(patName()), baseSelected ? 0 : indexAbove()); reg(pat.layer.rt); pat.layer.pending = true; changed = true;
  }
  if (engine.active !== pat.layer) { engine.active = pat.layer; changed = true; }
  baseSelected = false;
  if (changed) renderLayers();
  engine.clearOverlay(); engine.setOverlayMode(0, o.opacity);
  engine.pattern(patParams(), panels ? { islands: pat.sel } : null);
  markDirty();
}
function togglePatternPanel(hit) {
  const part = S.pattern.target === 'part';
  const ids = h => part ? islandsOfPart(h.part) : [h.island];
  const mine = ids(hit), add = !mine.every(i => pat.sel.has(i));
  const setAll = list => list.forEach(i => add ? pat.sel.add(i) : pat.sel.delete(i));
  setAll(mine);
  if (S.symmetry) { const mh = pickObject(M(hit.p), M(hit.n)); if (mh) setAll(ids(mh)); }
  previewPattern(); renderOptions();
}
function applyPattern() {
  const o = S.pattern;
  if (!pat.layer || engine.ovMode < 0) return toast(o.target === 'layer' ? 'Nothing to apply' : 'Click the panels you want on the car first');
  const L = pat.layer;
  if (L.pending) {
    delete L.pending;
    L.name = '\0'; L.name = uniqueName(patName());
    engine.commit(L)?.dispose();
    const idx = engine.layers.indexOf(L);
    hist.undo.push({ t: 'layers', before: engine.layers.filter(x => x !== L), after: engine.layers.slice(), activeBefore: engine.layers[idx - 1] || null, activeAfter: L });
    for (const r of hist.redo) forget(r); hist.redo.length = 0; gc(); projectDirty = true; updateUndoButtons();
    toast(`Applied as the layer "${L.name}"`, 'ok', 2000);
  } else {
    commitTo(L);
    toast(`Added to "${L.name}"`, 'ok', 2000);
  }
  pat.layer = null; pat.sel.clear();
  renderLayers(); renderOptions();
}
function cancelPattern({ keepSelection = false } = {}) {
  if (!engine) return;
  dropPending();
  pat.layer = null;
  if (!keepSelection) pat.sel.clear();
  engine.clearOverlay(); markDirty(); renderLayers();
}

// ---- eyedropper ---------------------------------------------------------------------------------
function eyedrop(hit) {
  if (!hit?.isPaint || !hit.uv) return;
  setColour(paintColourAt(hit));
  addRecent(S.color);
}

// ================================================================================================
// pointer / keyboard
// ================================================================================================
let spaceDown = false, hover = null, maybeDeselect = null;
view.addEventListener('pointerdown', onDown, true);          // capture phase: tools get first say, OrbitControls gets the rest
view.addEventListener('pointermove', onMove);
view.addEventListener('pointerup', onUp);
view.addEventListener('pointercancel', onUp);
view.addEventListener('pointerleave', () => { hover = null; });
addEventListener('pointerup', e => {
  if (maybeDeselect && Math.hypot(e.clientX - maybeDeselect.x, e.clientY - maybeDeselect.y) < 4) deselectDecal();
  maybeDeselect = null;
}, true);

function onDown(e) {
  if (!engine || e.button !== 0 || spaceDown || $('#modalWrap').classList.contains('show')) return;
  const consume = () => { e.preventDefault(); e.stopPropagation(); view.setPointerCapture(e.pointerId); };
  const hId = e.target?.dataset?.h;
  if (hId && handleGeom) { beginHandleDrag(e, hId); consume(); return; }
  if (pickFromCar) {                                               // "From car" in the colour picker
    const hp = pick(e.clientX, e.clientY);
    if (hp?.isPaint && hp.uv) { const c = paintColourAt(hp); pickFromCar(c, true); addRecent(c); }
    endPickFromCar(); consume(); renderOptions(); return;
  }
  if (S.tool === 'pen') { if (penDown(e)) consume(); return; }
  const hit = pick(e.clientX, e.clientY);
  if (!hit) return;                                              // background: orbit
  const t = S.tool;
  if (e.altKey && ['brush', 'eraser', 'line', 'fill', 'gradient', 'pattern'].includes(t)) { eyedrop(hit); consume(); return; }
  switch (t) {
    case 'brush': case 'eraser': beginStroke(e); break;
    case 'line': { const L = ensurePaintLayer(); warnLockedEmpty(L); engine.active = L; drag = { kind: 'line', layer: L, x0: e.clientX, y0: e.clientY }; lineTo(e); break; }
    case 'fill': if (hit.isPaint) doFill(hit); break;
    case 'gradient': if (!hit.isPaint && S.gradient.target !== 'layer') return; beginGradient(e, hit); break;
    case 'pattern':
      if (!hit.isPaint) return;
      drag = { kind: 'patfade', a: hit.p.clone(), hit, x0: e.clientX, y0: e.clientY, moved: false };
      break;
    case 'eyedropper': eyedrop(hit); break;
    case 'select': {
      const d = pickDecal(hit);
      if (!d) { maybeDeselect = { x: e.clientX, y: e.clientY }; return; }
      if (d.layer !== active()) setActive(d.layer, { switchTool: false });
      beginMove(e, d.layer, d.mirror, hit); break;
    }
    case 'shape': case 'text': case 'image': {
      const d = pickDecal(hit, t);
      if (d) { if (d.layer !== active()) setActive(d.layer); beginMove(e, d.layer, d.mirror); break; }
      if (!hit.isPaint) return;
      if (t === 'image' && !S.image.current) { toast('Pick a logo from the library or upload an image first'); break; }
      const L = createDecal(t, hit);
      if (t === 'shape') { drag = { kind: 'size', layer: L, start: hit.p.clone(), x0: e.clientX, y0: e.clientY }; pendingEdit = { layer: L, before: snap(L) }; }
      else beginMove(e, L, false);
      break;
    }
    default: return;
  }
  consume();
}
function beginMove(e, L, mirror, hit = null) {
  const c0 = isPath(L) ? L.decal.frames[0]?.c || pathCentroid(L.params) : V3(L.params.c), c = toScreen(mirror ? M(c0) : c0), r = view.getBoundingClientRect();
  drag = { kind: 'move', layer: L, mirror, off: { x: c.x + r.left - e.clientX, y: c.y + r.top - e.clientY },
           prev: hit ? (mirror ? M(hit.p) : hit.p.clone()) : null };
  if (pendingEdit?.layer !== L) { endEdit(); pendingEdit = { layer: L, before: snap(L) }; }
}
function beginHandleDrag(e, id) {
  const L = active(), r = view.getBoundingClientRect();
  endEdit(); pendingEdit = { layer: L, before: snap(L) };
  const { w, h } = decalSize(L.params, L.decal.aspect || 1);
  drag = { kind: 'handle', id, layer: L, g: { ...handleGeom }, w, h, rot: L.params.rot, x0: e.clientX - r.left, y0: e.clientY - r.top };
}
let regenQueued = false;
function onMove(e) {
  hover = { x: e.clientX, y: e.clientY, shift: e.shiftKey };
  if (!drag) return;
  const d = drag;
  if (d.kind === 'stroke') strokeTo(e);
  else if (d.kind === 'line') lineTo(e);
  else if (d.kind === 'grad') gradientTo(e);
  else if (d.kind.startsWith('pen-')) penMove(e);
  else if (d.kind === 'patfade') {
    if (!d.moved && Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 6) return;
    d.moved = true;
    const hit = pick(e.clientX, e.clientY), b = hit?.isPaint ? hit.p : planePoint(e.clientX, e.clientY, d.a);
    Object.assign(S.pattern, { fadeDir: 5, fadeA: d.a.toArray(), fadeB: b.toArray() });
    previewPattern();
    const r = view.getBoundingClientRect();
    Object.entries({ x1: d.x0 - r.left, y1: d.y0 - r.top, x2: e.clientX - r.left, y2: e.clientY - r.top }).forEach(([k, v]) => H.grad.setAttribute(k, v));
    H.grad.style.display = '';
  }
  else if (d.kind === 'move' && isPath(d.layer)) {                 // move a whole path along the body
    const hit = pick(e.clientX, e.clientY);
    if (!hit?.isPaint) return;
    const cur = d.mirror ? M(hit.p) : hit.p.clone();
    if (d.prev) { const delta = cur.clone().sub(d.prev); transformPath(d.layer.params, v => v.add(delta)); updateClip(d.layer.params); queueRegen(d.layer); }
    d.prev = cur;
  } else if (d.kind === 'move') {
    const hit = pick(e.clientX + d.off.x, e.clientY + d.off.y);
    if (!hit?.isPaint) return;
    const p = d.layer.params;
    p.c = (d.mirror ? M(hit.p) : hit.p).toArray(); p.n = (d.mirror ? M(hit.n) : hit.n).toArray();
    updateClip(p); refreshDecal(d.layer, false);
  } else if (d.kind === 'size') {
    const L = d.layer, p = L.params;
    if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 5) return;
    const hit = pick(e.clientX, e.clientY);
    const b = hit?.isPaint ? hit.p : planePoint(e.clientX, e.clientY, d.start);
    const f = L.decal.frames[0]; if (!f) return;
    const rel = b.clone().sub(d.start);
    let w = Math.abs(rel.dot(f.r)) * 2, h = Math.abs(rel.dot(f.u)) * 2;
    if (e.shiftKey || ['circle', 'star', 'polygon', 'ring', 'heart'].includes(p.shape.shape) && !e.altKey) { const s = Math.max(w, h); w = h = s; }
    setDecalWH(L, Math.max(w, 0.02), Math.max(h, 0.02));
    queueRegen(L);
  } else if (d.kind === 'handle') handleTo(e);
}
function queueRegen(L) {
  if (regenQueued) return; regenQueued = true;
  requestAnimationFrame(() => { regenQueued = false; refreshDecal(L, L.params.type === 'shape' || L.params.type === 'path'); });
}
function handleTo(e) {
  const d = drag, L = d.layer, p = L.params, g = d.g, r = view.getBoundingClientRect();
  const x = e.clientX - r.left, y = e.clientY - r.top;
  const v = { x: x - g.c.x, y: y - g.c.y }, v0 = { x: d.x0 - g.c.x, y: d.y0 - g.c.y };
  if (d.id === 'rot') {
    const da = Math.atan2(v.y, v.x) - Math.atan2(v0.y, v0.x);
    let rot = d.rot + da * 180 / Math.PI * (g.det < 0 ? 1 : -1);
    if (e.shiftKey) rot = Math.round(rot / 15) * 15;
    p.rot = ((rot + 540) % 360) - 180;
    refreshDecal(L, false);
  } else if (d.id.startsWith('c')) {
    const s = Math.hypot(v.x, v.y) / Math.max(1, Math.hypot(v0.x, v0.y));
    if (setDecalWH(L, d.w * s, d.h * s)) queueRegen(L); else refreshDecal(L, false);
  } else {
    const axis = d.id === 'e1' || d.id === 'e3' ? g.ax : g.ay;
    const al = Math.hypot(axis.x, axis.y) || 1;
    const t = Math.abs((v.x * axis.x + v.y * axis.y) / al) / Math.max(1, Math.abs((v0.x * axis.x + v0.y * axis.y) / al));
    const horizontal = axis === g.ax;
    const regen = setDecalWH(L, horizontal ? d.w * t : d.w, horizontal ? d.h : d.h * t);
    if (regen) queueRegen(L); else refreshDecal(L, false);
  }
}
function onUp() {
  const d = drag; if (!d) return;
  drag = null;
  if (d.kind === 'stroke' || d.kind === 'line') { if (d.drew) commitTo(d.layer); else { engine.clearOverlay(); markDirty(); } }
  else if (d.kind === 'grad') { H.grad.style.display = 'none'; commitTo(d.layer); }
  else if (d.kind === 'move' || d.kind === 'handle' || d.kind === 'size') { if (d.kind === 'size') refreshDecal(d.layer, true); endEdit(); renderOptions(); }
  else if (d.kind === 'patfade') {
    H.grad.style.display = 'none';
    if (d.moved) { saveSettings(); renderOptions(); }
    else if (S.pattern.target !== 'layer') togglePatternPanel(d.hit);
  }
  else if (d.kind.startsWith('pen-')) { refreshDecal(d.layer, true); if (!pen.drawing || d.kind !== 'pen-new') endEdit(); else endEdit(); }
}
function deselectDecal() {
  const L = active();
  if (L?.kind !== 'decal') return;
  endEdit();
  const below = engine.layers.slice(0, engine.layers.indexOf(L)).reverse().find(x => x.kind === 'paint');
  engine.active = below || null; baseSelected = false;
  renderLayers(); renderOptions();
}

addEventListener('wheel', e => {
  if (!engine || !view.contains(e.target)) return;
  const delta = e.deltaY || e.deltaX;
  if (!delta || !(e.shiftKey || e.altKey)) return;
  const L = active();
  if (isPath(L) && ['pen', 'select'].includes(S.tool)) {                // paths: scale / rotate around their centre
    e.preventDefault(); e.stopPropagation();
    const o = pathCentroid(L.params);
    if (e.altKey) { const q = new THREE.Quaternion().setFromAxisAngle(V3(L.params.pn).normalize(), (delta > 0 ? -5 : 5) * Math.PI / 180); editLayer(L, x => transformPath(x.params, v => v.sub(o).applyQuaternion(q).add(o)), false, true); }
    else { const k = delta > 0 ? 1 / 1.08 : 1.08; editLayer(L, x => transformPath(x.params, v => v.sub(o).multiplyScalar(k).add(o)), false, true); }
    clearTimeout(wheelTimer); wheelTimer = setTimeout(() => { endEdit(); renderOptions(); }, 400);
    return;
  }
  const decalTool = L?.kind === 'decal' && showHandles();
  if (e.altKey && decalTool) {
    e.preventDefault(); e.stopPropagation();
    editLayer(L, x => { x.params.rot = ((x.params.rot + (delta > 0 ? 5 : -5) + 540) % 360) - 180; }, false);
    clearTimeout(wheelTimer); wheelTimer = setTimeout(() => { endEdit(); renderOptions(); }, 400);
  } else if (e.shiftKey) {
    e.preventDefault(); e.stopPropagation();
    const k = delta > 0 ? 1 / 1.1 : 1.1;
    if (decalTool) {
      const { w, h } = decalSize(L.params, L.decal.aspect || 1);
      editLayer(L, x => { setDecalWH(x, w * k, h * k); }, false, L.params.type === 'shape');
      clearTimeout(wheelTimer); wheelTimer = setTimeout(() => { endEdit(); renderOptions(); }, 400);
    } else if (['brush', 'eraser', 'line'].includes(S.tool)) { S[S.tool].size = clamp(S[S.tool].size * k, 0.002, 1.5); saveSettings(); refreshSizeSlider(); }
  }
}, { capture: true, passive: false });
let wheelTimer;
function refreshSizeSlider() { document.querySelector('#opts [data-size]')?.refresh?.(); }

addEventListener('keydown', e => {
  if ($('#modalWrap').classList.contains('show')) { if (e.key === 'Escape') closeModal(); return; }
  if (e.key === 'Escape' && picker.el?.style.display === 'block') { closePicker(); return; }
  if (e.key === 'Escape' && pickFromCar) { endPickFromCar(); return; }
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) && document.activeElement.type !== 'range' && document.activeElement.type !== 'checkbox';
  const k = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && k === 's') { e.preventDefault(); saveProject(); return; }
  if (typing) return;
  if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); redo(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (k === ' ') { spaceDown = true; e.preventDefault(); renderer.domElement.style.cursor = 'grab'; return; }
  const tool = TOOLS.find(t => t && t[2] === k);
  if (tool) { setTool(tool[0]); return; }
  if (k === 'x') { toggleSymmetry(); return; }
  if (k === '[' || k === ']') {
    const f = k === ']' ? 1.15 : 1 / 1.15;
    if (['brush', 'eraser', 'line'].includes(S.tool)) { S[S.tool].size = clamp(S[S.tool].size * f, 0.002, 1.5); saveSettings(); refreshSizeSlider(); }
    return;
  }
  if (k === 'enter') { if (pen.drawing) finishPath(); else if (S.tool === 'pattern') applyPattern(); else deselectDecal(); return; }
  if (k === 'escape') {
    if (pen.drawing) finishPath();
    else if (S.tool === 'pen' && pen.sel) { pen.sel = null; renderOptions(); }
    else if (S.tool === 'pattern') { cancelPattern(); renderOptions(); }
    else deselectDecal();
    return;
  }
  if ((k === 'delete' || k === 'backspace') && S.tool === 'pen' && activePath() && pen.sel) { e.preventDefault(); deletePathPoint(activePath()); return; }
  if ((k === 'delete' || k === 'backspace') && active()?.kind === 'decal') { deleteLayer(); return; }
});
addEventListener('keyup', e => { if (e.key === ' ') { spaceDown = false; renderer.domElement.style.cursor = ''; } });
// buttons keep no keyboard focus after a click, so Space / Enter shortcuts don't press them again
addEventListener('pointerup', e => { const b = e.target.closest?.('button'); if (b && !b.closest('#modal')) setTimeout(() => b.blur(), 0); });
function toggleSymmetry() { S.symmetry = !S.symmetry; saveSettings(); $('#symBtn').classList.toggle('on', S.symmetry); toast(`Symmetry ${S.symmetry ? 'on: everything is mirrored to the other side' : 'off'}`, '', 1800); }

// cursor ring that shows the brush on the surface
function updateCursor() {
  rings.forEach(r => { r.visible = false; });
  if (!hover || !engine || drag?.kind === 'move' || spaceDown) { renderer.domElement.style.cursor = spaceDown ? 'grab' : ''; return; }
  const t = S.tool;
  const hit = pick(hover.x, hover.y);
  let cursor = hit ? 'crosshair' : 'grab';
  if (['brush', 'eraser', 'line'].includes(t) && hit?.isPaint) {
    const r = S[t].size;
    const place = (ring, p, n) => {
      const wn = toWorldDir(n).normalize();
      ring.position.copy(car.group.localToWorld(p.clone())).addScaledVector(wn, 0.002);
      ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), wn); ring.scale.setScalar(r); ring.visible = true;
    };
    place(rings[0], hit.p, hit.n);
    if (S.symmetry) place(rings[1], M(hit.p), M(hit.n));
    cursor = 'none';
  } else if (['select', 'shape', 'text', 'image'].includes(t) && hit && pickDecal(hit, t === 'select' ? null : t)) cursor = 'move';
  else if (['fill', 'eyedropper', 'gradient', 'pattern', 'shape', 'text', 'image'].includes(t) && hit && !hit.isPaint) cursor = 'not-allowed';
  renderer.domElement.style.cursor = cursor;
}

// ================================================================================================
// tool options panel
// ================================================================================================
function renderOptions() {
  const box = $('#opts'); box.innerHTML = '';
  if (!engine) return;
  const t = S.tool;
  const title = { select: 'Select', brush: 'Brush', eraser: 'Eraser', fill: 'Paint bucket', line: 'Line', gradient: 'Gradient',
                  pattern: 'Patterns & textures', shape: 'Shapes', text: 'Text', image: 'Images & logos', eyedropper: 'Pick colour', pen: 'Pen' }[t];
  box.append(el('h3', {}, title));
  if (['brush', 'line', 'fill', 'eyedropper'].includes(t)) box.append(colourBlock());
  const o = S[t];
  const set = (k, after) => (v, fin = true) => { o[k] = v; saveSettings(); after?.(v, fin); };
  if (t === 'brush' || t === 'eraser' || t === 'line') {
    const sz = slider(t === 'line' ? 'Width' : 'Size', () => o.size * 2, (v) => { o.size = v / 2; saveSettings(); }, { min: 0.004, max: 3, log: true, fmt: cm });
    sz.dataset.size = '1'; box.append(sz);
    box.append(slider('Hardness', () => o.hardness, set('hardness'), { min: 0, max: 1, fmt: pct }));
    box.append(slider('Opacity', () => o.opacity, set('opacity'), { min: 0.02, max: 1, fmt: pct }));
    box.append(check('Don\'t cross panel edges', o.protect, set('protect')));
    if (t === 'brush') box.append(check('Pen pressure changes size', o.pressure, set('pressure')));
    if (t === 'eraser') box.append(el('div', { class: 'note' }, 'Erases the selected paint layer only.'));
  } else if (t === 'fill') {
    box.append(seg('Fill', [['panel', 'Panel'], ['part', 'Part'], ['layer', 'Whole car']], () => o.target, set('target')));
    const sel = el('select', { class: 'fill', onchange: async e => { o.with = e.target.value; const tx = TEXTURES[o.with]; if (tx) { o.c1 = tx.c1; o.c2 = tx.c2; } saveSettings(); renderOptions(); } },
      el('option', { value: 'colour', selected: o.with === 'colour' }, 'Main colour'),
      Object.entries(TEXTURES).map(([k, v]) => el('option', { value: k, selected: o.with === k }, v.name)));
    box.append(row('With', sel));
    if (o.with !== 'colour') {
      box.append(colour('Colour 1', () => o.c1, set('c1')), colour('Colour 2', () => o.c2, set('c2')));
      box.append(slider('Scale', () => o.scale, set('scale'), { min: 0.25, max: 4, log: true, fmt: v => v.toFixed(2) + '×' }));
      box.append(slider('Angle', () => o.angle, set('angle'), { min: -90, max: 90, step: 1, fmt: v => Math.round(v) + '°' }));
    }
    box.append(slider('Opacity', () => o.opacity, set('opacity'), { min: 0.02, max: 1, fmt: pct }));
    box.append(el('div', { class: 'note' }, baseSelected ? 'Car base is selected: the fill goes on a "Base paint" layer under all your other layers.'
      : 'Tip: tick "Lock transparency" on a layer to recolour what is already painted on it.'));
  } else if (t === 'gradient') {
    box.append(seg('Type', [['linear', 'Linear'], ['radial', 'Radial'], ['reflected', 'Reflected']], () => o.type, set('type')));
    box.append(seg('Apply to', [['panel', 'Panel'], ['part', 'Part'], ['layer', 'Whole car']], () => o.target, set('target')));
    box.append(el('h4', {}, 'Colours'));
    gradStops();
    box.append(gradientEditor(o, fin => { if (fin) saveSettings(); }));
    box.append(el('div', { class: 'note', style: 'margin:8px 0 4px' }, 'Presets'));
    box.append(el('div', { class: 'seg' }, Object.keys(GRADIENT_PRESETS).map(n => el('button', { onclick: () => { o.stops = presetStops(n); gSel = 0; saveSettings(); renderOptions(); } }, n))));
    box.append(seg('Blend', [['smooth', 'Smooth'], ['linear', 'Linear'], ['hard', 'Hard bands']], () => o.blend, v => { o.blend = v; saveSettings(); renderOptions(); }));
    box.append(slider('Repeat', () => o.repeat || 1, (v, fin) => { o.repeat = Math.round(v); saveSettings(); if (fin) renderOptions(); }, { min: 1, max: 20, step: 1, fmt: v => Math.round(v) + '×' }));
    const cur = active();
    if (cur) box.append(check(cur.kind === 'decal' ? `Only on "${cur.name}" (turns it into a paint layer)` : `Only where "${cur.name}" already has paint`, o.clip, set('clip')));
    else if (baseSelected) box.append(el('div', { class: 'note' }, 'Car base is selected: the gradient goes on a "Base paint" layer under all your other layers. Choose Whole car to cover the entire car.'));
    box.append(el('div', { class: 'note' }, 'Drag across the car: the first colour starts where you press, the last one ends where you let go.'));
  } else if (t === 'pattern') patternOptions(box, o);
  else if (t === 'shape') shapeOptions(box);
  else if (t === 'text') textOptions(box);
  else if (t === 'image') imageOptions(box);
  else if (t === 'select') {
    if (active()?.kind !== 'decal') box.append(el('div', { class: 'note' }, 'Click a text, shape or image on the car to select it.'));
  }
  else if (t === 'pen') penOptions(box);
  if (['select', 'shape', 'text', 'image'].includes(t) && active()?.kind === 'decal' && (t === 'select' || active().params.type === t)) {
    if (isPath(active())) pathOptions(box, active()); else transformOptions(box, active());
  }
}

function patternOptions(box, o) {
  const upd = (k, rerender) => (v) => { o[k] = v; saveSettings(); previewPattern(); if (rerender) renderOptions(); };
  const sel = el('select', { class: 'fill', onchange: e => upd('type', true)(+e.target.value) },
    PATTERNS.map((n, i) => el('option', { value: i, selected: o.type === i }, n)));
  box.append(row('Pattern', sel));
  box.append(el('div', { class: 'seg', style: 'margin:4px 0 8px' }, Object.entries(TEXTURES).map(([k, tx]) => el('button', { onclick: () => {
    Object.assign(o, { type: tx.type, spacing: tx.spacing, c1: tx.c1, c2: tx.c2, two: !!tx.two, size: tx.size ?? 0.6, spread: 0, drop: 0 });
    saveSettings(); previewPattern(); renderOptions(); } }, tx.name))));
  box.append(colour('Colour 1', () => o.c1, upd('c1')));
  box.append(check('Second colour', o.two, upd('two', true)));
  if (o.two) box.append(colour('Colour 2', () => o.c2, upd('c2')));
  box.append(slider('Scale', () => o.spacing, upd('spacing'), { min: 0.01, max: 1.5, log: true, fmt: cm }));
  box.append(slider('Size', () => o.size, upd('size'), { min: 0.02, max: 1.4, fmt: pct }));
  box.append(slider('Angle', () => o.angle, upd('angle'), { min: -180, max: 180, step: 1, fmt: v => Math.round(v) + '°' }));
  box.append(slider('Jitter', () => o.spread, upd('spread'), { min: 0, max: 1, fmt: pct }));
  box.append(slider('Gaps', () => o.drop, upd('drop'), { min: 0, max: 0.95, fmt: pct }));
  box.append(row('Variation', el('button', { onclick: () => upd('seed')(Math.round(Math.random() * 1000) / 10) }, '🎲 Shuffle')));
  box.append(seg('Projection', [[0, 'Auto'], [1, 'Side'], [2, 'Top'], [3, 'Front']], () => o.proj, upd('proj')));
  box.append(el('h4', {}, 'Fade (dense → sparse)'));
  box.append(seg(null, [[0, 'None'], [2, 'Rear → front'], [1, 'Front → rear'], [3, 'Bottom → top'], [4, 'Top → bottom'], [5, 'Your own']],
    () => o.fadeDir, v => { if (v === 5 && !o.fadeA) toast('Drag on the car: it is densest where you start and fades out where you let go', '', 5000); upd('fadeDir', true)(v); }));
  box.append(el('div', { class: 'note' }, 'Or drag on the car to set the fade yourself: densest where you start, gone where you let go.'));
  if (o.fadeDir) {
    box.append(seg(null, [['linear', 'Along a line'], ['radial', 'Out from a point']], () => o.fadeShape, upd('fadeShape', true)));
    const fx = (bit, label) => check(label, (o.fadeFx & bit) !== 0, v => upd('fadeFx', true)(v ? o.fadeFx | bit : o.fadeFx & ~bit));
    box.append(el('div', { class: 'note', style: 'margin:8px 0 2px' }, 'What fades'));
    box.append(fx(2, 'Fewer shapes (density)'), fx(1, 'Smaller shapes'), fx(4, 'More transparent'));
    box.append(slider('Full until', () => o.fadeStart, upd('fadeStart'), { min: 0, max: 1, fmt: pct }));
    box.append(slider('Gone by', () => o.fadeEnd, upd('fadeEnd'), { min: 0, max: 1, fmt: pct }));
    box.append(slider('Curve', () => o.fadeCurve, upd('fadeCurve'), { min: 0.25, max: 4, log: true, fmt: v => v < 0.95 ? 'slow' : v > 1.05 ? 'fast' : 'even' }));
  }
  box.append(slider('Opacity', () => o.opacity, upd('opacity'), { min: 0.02, max: 1, fmt: pct }));
  box.append(seg('Apply to', [['layer', 'Whole car'], ['panel', 'Panels'], ['part', 'Parts']], () => o.target, v => { o.target = v; saveSettings(); pat.sel.clear(); cancelPattern(); previewPattern(); renderOptions(); }));
  if (o.target !== 'layer') {
    const n = pat.sel.size;
    box.append(el('div', { class: 'note' + (n ? '' : ' warn') }, n
      ? `${n} panel${n > 1 ? 's' : ''} selected. Click more ${o.target === 'part' ? 'parts' : 'panels'} to add them, click again to remove.`
      : `Click the ${o.target === 'part' ? 'parts' : 'panels'} you want on the car (as many as you like).`));
    if (n) box.append(el('button', { onclick: () => { pat.sel.clear(); previewPattern(); renderOptions(); } }, 'Clear selection'));
  }
  const cur = active()?.kind === 'paint' && !active().pending ? active() : pat.target && engine.layers.includes(pat.target) ? pat.target : null;
  box.append(seg('Put it on', [['new', 'A new layer'], ['current', cur ? `"${cur.name}"` : 'The selected layer']], () => o.into, v => {
    o.into = v; saveSettings(); pat.target = cur; cancelPattern({ keepSelection: true }); previewPattern(); renderOptions(); }));
  box.append(el('div', { class: 'row', style: 'margin-top:12px' },
    el('button', { class: 'accent', onclick: applyPattern }, 'Apply  (Enter)'),
    el('button', { onclick: () => { cancelPattern(); renderOptions(); previewPattern(); } }, 'Reset')));
  const onBase = (baseSelected || pat.fromBase && pat.layer?.pending) && o.into === 'new';
  box.append(el('div', { class: 'note' }, onBase ? 'Car base is selected: applies as its own layer right above the base, under all your other layers.'
    : o.into === 'new' ? 'Applies as its own layer, so you can change its opacity and finish afterwards.' : 'Applies onto the selected paint layer. Pick that layer in the list first.'));
}

// decal option panels edit the selected decal when it matches the tool, otherwise the defaults for the next one
function decalTarget(type) { const L = active(); return L?.kind === 'decal' && L.params.type === type ? L : null; }
function decalSetter(type, regen = true) {
  return (k, rerender) => (v, fin = true) => {
    S[type][k] = v; saveSettings();
    const L = decalTarget(type);
    if (L) editLayer(L, x => { x.params[type][k] = v; if (type === 'text' && k === 'text') x.name = 'Text: ' + String(v).split('\n')[0].slice(0, 18); }, fin, regen);
    if (rerender && fin) renderOptions();
    if (type === 'text' && k === 'text' && fin) renderLayers(false);
  };
}
const shapeThumbs = new Map();
function shapeThumb(id, custom) {
  const key = id + (custom ? JSON.stringify(custom.pts) + custom.smooth : '');
  if (!shapeThumbs.has(key)) {
    const big = ST.renderShape({ shape: id, custom, color: '#d9dde3', aspect: id === 'stripes' || id === 'speed' || id === 'arrow' || id === 'darrow' ? 1.6 : 1, thickness: 0.3, sides: 6, points: 5, inner: 0.45, slant: 0.3, radius: 0.2 }).canvas;
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const s = 56 / Math.max(big.width, big.height);
    c.getContext('2d').drawImage(big, (64 - big.width * s) / 2, (64 - big.height * s) / 2, big.width * s, big.height * s);
    shapeThumbs.set(key, c);
  }
  const src = shapeThumbs.get(key), c = document.createElement('canvas'); c.width = c.height = 64; c.getContext('2d').drawImage(src, 0, 0);
  return c;
}
const customShapes = () => store.get('customShapes', []);
function shapeOptions(box) {
  const L = decalTarget('shape'), o = L ? L.params.shape : S.shape, set = decalSetter('shape');
  const grid = el('div', { class: 'grid' });
  const choose = (id, custom, name) => {
    S.shape.shape = id; S.shape.custom = custom || null; S.shape.customName = name || null; saveSettings();
    if (L) editLayer(L, x => { Object.assign(x.params.shape, { shape: id, custom: custom || null, customName: name || null }); x.name = uniqueName(name || ST.SHAPES[id].name); }, true, true);
    renderOptions(); renderLayers(false);
  };
  for (const [id, sh] of Object.entries(ST.SHAPES)) grid.append(el('button', { title: sh.name, class: o.shape === id ? 'on' : '', onclick: () => choose(id) }, shapeThumb(id)));
  for (const cs of customShapes()) {
    const b = el('button', { title: cs.name + ' (right-click to edit)', class: o.shape === 'custom' && o.customName === cs.name ? 'on' : '', onclick: () => choose('custom', { pts: cs.pts, smooth: cs.smooth }, cs.name),
      oncontextmenu: e => { e.preventDefault(); shapeEditor(cs); } }, shapeThumb('custom', cs));
    grid.append(b);
  }
  grid.append(el('button', { title: 'Draw your own shape', onclick: () => shapeEditor(), style: 'font-size:20px' }, '＋'));
  box.append(grid);
  box.append(colour('Colour', () => o.color, set('color')));
  box.append(slider('Outline', () => o.outline, set('outline'), { min: 0, max: 0.3, fmt: pct }));
  box.append(colour('Outline colour', () => o.outlineColor, set('outlineColor')));
  const params = o.shape === 'custom' ? [] : ST.SHAPES[o.shape]?.params || [];
  if (params.includes('radius')) box.append(slider('Corner radius', () => o.radius, set('radius'), { min: 0, max: 1, fmt: pct }));
  if (params.includes('thickness')) box.append(slider('Thickness', () => o.thickness, set('thickness'), { min: 0.05, max: 0.95, fmt: pct }));
  if (params.includes('sides')) box.append(slider('Sides', () => o.sides, set('sides'), { min: 3, max: 12, step: 1, fmt: v => Math.round(v) }));
  if (params.includes('points')) box.append(slider('Points', () => o.points, set('points'), { min: 3, max: 16, step: 1, fmt: v => Math.round(v) }));
  if (params.includes('inner')) box.append(slider('Inner size', () => o.inner, set('inner'), { min: 0.1, max: 0.9, fmt: pct }));
  if (params.includes('slant')) box.append(slider('Slant', () => o.slant, set('slant'), { min: 0, max: 0.9, fmt: pct }));
  if (!L) box.append(el('div', { class: 'note' }, 'Click the car to place it, or click and drag to draw it at a size.'));
}
function fontSelect(o, set) {
  const sel = el('select', { class: 'fill', onchange: async e => {
    if (e.target.value === '__other') {
      const name = await askText('Name of a font installed on this PC');
      if (name?.trim()) { S.customFonts = [...new Set([...S.customFonts, name.trim()])]; set('font', true)(name.trim()); }
      else renderOptions();
      return;
    }
    set('font')(e.target.value);
  } });
  const opt = f => el('option', { value: f, selected: o.font === f, style: `font-family:"${f}"` }, f);
  sel.append(el('optgroup', { label: 'Racing fonts' }, ST.GOOGLE_FONTS.map(opt)));
  sel.append(el('optgroup', { label: 'Installed on this PC' }, [...availableSystemFonts(), ...S.customFonts].map(opt)));
  if (![...ST.GOOGLE_FONTS, ...availableSystemFonts(), ...S.customFonts].includes(o.font)) sel.append(opt(o.font));
  sel.append(el('option', { value: '__other' }, 'Other installed font…'));
  return sel;
}
let sysFonts = null;
const availableSystemFonts = () => (sysFonts ??= ST.SYSTEM_FONTS.filter(ST.systemFontAvailable));
function textOptions(box) {
  const L = decalTarget('text'), o = L ? L.params.text : S.text, set = decalSetter('text');
  const ta = el('textarea', { value: o.text, rows: 2, placeholder: 'Your text' });
  ta.addEventListener('input', () => set('text')(ta.value, false));
  ta.addEventListener('change', () => set('text')(ta.value, true));
  box.append(ta);
  box.append(row('Font', fontSelect(o, set)));
  box.append(el('div', { class: 'seg', style: 'margin:4px 0' },
    el('button', { class: o.bold ? 'on' : '', onclick: () => set('bold', true)(!o.bold), style: 'font-weight:700' }, 'B'),
    el('button', { class: o.italic ? 'on' : '', onclick: () => set('italic', true)(!o.italic), style: 'font-style:italic' }, 'I'),
    ...[['left', 'Left'], ['center', 'Centre'], ['right', 'Right']].map(([v, n]) => el('button', { class: o.align === v ? 'on' : '', onclick: () => set('align', true)(v) }, n))));
  box.append(colour('Colour', () => o.color, set('color')));
  box.append(slider('Outline', () => o.outline, set('outline'), { min: 0, max: 0.25, fmt: pct }));
  box.append(colour('Outline colour', () => o.outlineColor, set('outlineColor')));
  box.append(slider('Spacing', () => o.spacing, set('spacing'), { min: -0.1, max: 0.6, fmt: v => v.toFixed(2) }));
  box.append(slider('Slant', () => o.skew, set('skew'), { min: -30, max: 30, step: 1, fmt: v => Math.round(v) + '°' }));
  box.append(slider('Stretch', () => o.stretch, set('stretch'), { min: 0.4, max: 2.5, fmt: v => v.toFixed(2) + '×' }));
  if (o.text.includes('\n')) box.append(slider('Line spacing', () => o.lineHeight, set('lineHeight'), { min: 0.6, max: 2, fmt: v => v.toFixed(2) }));
  box.append(el('h4', {}, 'Number board / background'));
  box.append(seg(null, [['none', 'None'], ['box', 'Box'], ['rounded', 'Rounded'], ['pill', 'Pill'], ['circle', 'Circle'], ['oval', 'Oval']], () => o.board, v => {
    if (o.board === 'none' && v !== 'none' && o.color.toLowerCase() === o.boardColor.toLowerCase())   // keep the number readable
      set('color')(rawColor(o.boardColor).getHSL({}).l > 0.5 ? '#111111' : '#ffffff');
    set('board', true)(v);
  }));
  if (o.board !== 'none') {
    box.append(colour('Board colour', () => o.boardColor, set('boardColor')));
    box.append(slider('Padding', () => o.boardPad, set('boardPad'), { min: 0, max: 1, fmt: v => v.toFixed(2) }));
    box.append(slider('Board outline', () => o.boardOutline, set('boardOutline'), { min: 0, max: 0.2, fmt: pct }));
    box.append(colour('Outline colour', () => o.boardOutlineColor, set('boardOutlineColor')));
  }
  if (!L) box.append(el('div', { class: 'note' }, 'Click the car to place the text.'));
}

let decalLib = null;
async function loadLibrary(force) {
  if (!decalLib || force) { try { decalLib = await api('api/decals'); } catch { decalLib = []; } }
  return decalLib;
}
function imageOptions(box) {
  const L = decalTarget('image');
  const o = L ? L.params.image : S.image;
  box.append(el('div', { class: 'row' },
    el('button', { class: 'accent', onclick: () => pickFile(f => useUploadedImage(f)) }, 'Upload image…'),
    el('span', { class: 'note', style: 'margin:0' }, L ? '' : (S.image.current ? 'Ready: ' + S.image.current.name : ''))));
  if (L || S.image.current) {
    box.append(el('h4', {}, 'Background removal'));
    const setCut = (k, rerender) => (v, fin = true) => {
      S.image.cut[k] = v; saveSettings();
      if (L) editLayer(L, x => { x.params.image.cut[k] = v; }, fin, true);
      if (rerender && fin) renderOptions();
    };
    box.append(seg(null, [['off', 'Off'], ['auto', 'Auto'], ['white', 'White'], ['black', 'Black']], () => o.cut.mode, v => setCut('mode', true)(v)));
    if (o.cut.mode !== 'off') {
      box.append(slider('Tolerance', () => o.cut.tolerance, setCut('tolerance'), { min: 1, max: 60, step: 1, fmt: v => Math.round(v) }));
      box.append(slider('Soft edge', () => o.cut.feather, setCut('feather'), { min: 0, max: 40, step: 1, fmt: v => Math.round(v) }));
      box.append(check('Only the background touching the edges', o.cut.connected, v => setCut('connected', true)(v)));
    }
    const setTint = (k, rerender) => (v, fin = true) => { S.image[k] = v; saveSettings(); if (L) editLayer(L, x => { x.params.image[k] = v; }, fin); if (rerender) renderOptions(); };
    box.append(check('Recolour (one-colour logos)', o.tint, v => setTint('tint', true)(v)));
    if (o.tint) box.append(colour('Colour', () => o.tintColor, setTint('tintColor')));
    if (L) box.append(el('button', { style: 'margin-top:6px', onclick: () => saveToLibrary(L) }, 'Save to my decals'));
  }
  box.append(el('h4', {}, 'Decal library'));
  box.append(el('div', { class: 'seg', style: 'margin-bottom:8px' },
    el('button', { title: 'A zip full of logos, or several image files at once', onclick: () => pickFiles(importLogos, '.zip,application/zip,image/png,image/svg+xml,image/jpeg,image/webp') }, '⇪ Import logos (zip or images)…'),
    el('button', { title: 'Open the decals folder in Explorer', onclick: () => api('api/decals/open', { method: 'POST' }).catch(e => toast(e.message, 'err')) }, 'Open folder')));
  const libBox = el('div', {}, el('div', { class: 'note' }, 'Loading…'));
  box.append(libBox);
  loadLibrary().then(list => {
    libBox.innerHTML = '';
    if (!list.length) { libBox.append(el('div', { class: 'note' }, 'No decals found.')); return; }
    const cats = [...new Set(list.map(d => d.category))];
    let cat = store.get('libCat', 'All'); if (!cats.includes(cat)) cat = 'All';
    const search = el('input', { type: 'text', placeholder: 'Search…', style: 'width:100%;margin-bottom:6px' });
    const catSel = el('select', { style: 'width:100%;margin-bottom:6px' }, ['All', ...cats].map(c => el('option', { value: c, selected: c === cat }, c)));
    const grid = el('div', { class: 'lib' });
    const draw = () => {
      grid.innerHTML = '';
      const q = search.value.trim().toLowerCase();
      for (const d of list) {
        if (catSel.value !== 'All' && d.category !== catSel.value) continue;
        if (q && !d.name.toLowerCase().includes(q)) continue;
        grid.append(el('button', { title: d.name, onclick: () => useLibraryImage(d) }, el('img', { src: d.thumb || d.url, loading: 'lazy', alt: d.name })));
      }
      if (!grid.firstChild) grid.append(el('div', { class: 'note', style: 'grid-column:1/-1' }, 'Nothing matches.'));
    };
    catSel.addEventListener('change', () => { store.set('libCat', catSel.value); draw(); });
    search.addEventListener('input', draw);
    libBox.append(el('div', { class: 'note', style: 'margin:0 0 6px' }, `${list.length} logos in ${cats.length} folders`), search, catSel, grid,
      el('div', { class: 'note' }, 'Logos also load from the "decals" folder next to the editor (PNG, SVG, JPG). After adding files there, ',
        el('a', { href: '#', style: 'color:var(--accent)', onclick: e => { e.preventDefault(); loadLibrary(true).then(() => renderOptions()); } }, 'refresh'), '.'));
    draw();
  });
}
async function useLibraryImage(d) {
  const L = decalTarget('image');
  let auto = false;
  try { auto = solidBackground(await sourceCanvas(d.url)); } catch {}
  S.image.current = { src: d.url, name: d.name }; S.image.cut.mode = auto ? 'auto' : 'off'; saveSettings();
  if (L) { editLayer(L, x => { Object.assign(x.params.image, { src: d.url, name: d.name, cut: structuredClone(S.image.cut) }); x.name = uniqueName(d.name); }, true, true); renderLayers(false); }
  else toast(`Click the car to place "${d.name}"${auto ? ' (its background will be removed)' : ''}`, '', 3000);
  renderOptions();
}
/** True when an image sits on a flat, opaque background we can cut out (a white box around a logo, say). */
function solidBackground(canvas) {
  const d = canvas.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, canvas.width, canvas.height).data;
  let edgeAlpha = 0, n = 0;
  for (let x = 0; x < canvas.width; x += 4) { edgeAlpha += d[x * 4 + 3] + d[((canvas.height - 1) * canvas.width + x) * 4 + 3]; n += 2; }
  return !!ST.borderColor(d, canvas.width, canvas.height) && edgeAlpha / n > 250;
}
function pickFiles(cb, accept) {
  const inp = $('#fileInput'); inp.accept = accept; inp.multiple = true; inp.value = '';
  inp.onchange = () => { const files = [...inp.files]; inp.multiple = false; if (files.length) cb(files); };
  inp.click();
}
async function importLogos(files) {
  const zips = files.filter(f => /\.zip$/i.test(f.name)), images = files.filter(f => !/\.zip$/i.test(f.name));
  let added = 0, existing = 0, skipped = [], folder = null;
  await busy(`Importing ${files.length === 1 ? files[0].name : files.length + ' files'}…`);
  try {
    for (const z of zips) {
      const res = await api('api/decals/import?name=' + encodeURIComponent(z.name), { method: 'POST', body: z });
      added += res.added; existing += res.existing; skipped.push(...res.skipped); folder = res.folder;
    }
    for (const f of images) {
      const nm = f.name.replace(/\.[^.]+$/, '');
      const blob = /\.png$/i.test(f.name) ? f : await new Promise(ok => ST.loadImage(URL.createObjectURL(f)).then(img => ST.toCanvas(img, 4096).toBlob(ok, 'image/png')));
      await api('api/decals?name=' + encodeURIComponent(nm), { method: 'POST', body: blob }); added++; folder = folder || 'My decals';
    }
  } catch (e) { await busy(false); return toast('Import failed: ' + e.message, 'err', 8000); }
  await busy(false);
  if (folder) store.set('libCat', 'All');
  await loadLibrary(true); renderOptions();
  toast(`Imported ${added} logo${added === 1 ? '' : 's'}${folder ? ` into "${folder}"` : ''}` +
        (existing ? `, ${existing} already there` : '') + (skipped.length ? `, ${skipped.length} file${skipped.length === 1 ? '' : 's'} skipped (not images)` : ''), 'ok', 6000);
}
function pickFile(cb, accept = 'image/*') {
  const inp = $('#fileInput'); inp.accept = accept; inp.value = '';
  inp.onchange = () => inp.files[0] && cb(inp.files[0]);
  inp.click();
}
function readAsDataURL(f) { return new Promise((ok, fail) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = fail; r.readAsDataURL(f); }); }
async function useUploadedImage(file) {
  const src = await readAsDataURL(file), name = file.name.replace(/\.[^.]+$/, '');
  let canvas;
  try { canvas = await sourceCanvas(src); } catch (e) { return toast(e.message, 'err'); }
  // a solid border means a background we can cut out automatically
  const d = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  const opaqueBorder = ST.borderColor(d, canvas.width, canvas.height);
  let edgeAlpha = 0, n = 0;
  for (let x = 0; x < canvas.width; x += 4) { edgeAlpha += d[x * 4 + 3]; n++; }
  const auto = opaqueBorder && edgeAlpha / n > 250 && solidBackground(canvas);
  S.image.current = { src, name }; S.image.cut.mode = auto ? 'auto' : 'off'; saveSettings();
  const L = decalTarget('image');
  if (L) { editLayer(L, x => { Object.assign(x.params.image, { src, name, cut: structuredClone(S.image.cut) }); x.name = uniqueName(name); }, true, true); renderLayers(false); }
  toast(auto ? 'Background removed automatically. Set "Background removal" to Off to keep it.' : (L ? 'Image replaced' : 'Click the car to place your image'), '', 4500);
  renderOptions();
}
async function saveToLibrary(L) {
  const canvas = await decalCanvas(L.params);
  const name = await askText('Name for this decal', L.params.image.name || 'My logo');
  if (!name) return;
  const blob = await new Promise(r => canvas.toBlob(r, 'image/png'));
  try {
    await api('api/decals?name=' + encodeURIComponent(name), { method: 'POST', body: blob });
    toast('Saved to "My decals"', 'ok'); await loadLibrary(true); renderOptions();
  } catch (e) { toast('Could not save: ' + e.message, 'err'); }
}

function transformOptions(box, L) {
  const p = L.params;
  box.append(el('hr'), el('h3', {}, 'Placement'));
  const ed = (fn, fin, regen = false) => editLayer(L, fn, fin, regen);
  const { w, h } = decalSize(p, L.decal.aspect || 1);
  box.append(slider('Height', () => p.h, (v, fin) => { const { w: w0, h: h0 } = decalSize(p, L.decal.aspect || 1); ed(x => setDecalWH(x, w0 * v / h0, v), fin, p.type === 'shape'); }, { min: 0.01, max: 4, log: true, fmt: cm }));
  box.append(slider('Width', () => decalSize(p, L.decal.aspect || 1).w, (v, fin) => { ed(x => setDecalWH(x, v, x.params.h), fin, p.type === 'shape'); }, { min: 0.01, max: 6, log: true, fmt: cm }));
  box.append(slider('Rotation', () => p.rot, (v, fin) => ed(x => { x.params.rot = v; }, fin), { min: -180, max: 180, step: 1, fmt: v => Math.round(v) + '°' }));
  box.append(el('div', { class: 'seg', style: 'margin:4px 0' },
    el('button', { onclick: () => { ed(x => { x.params.rot = ((x.params.rot - 90 + 540) % 360) - 180; }); renderOptions(); } }, '⟲ 90°'),
    el('button', { onclick: () => { ed(x => { x.params.rot = ((x.params.rot + 90 + 540) % 360) - 180; }); renderOptions(); } }, '⟳ 90°'),
    el('button', { class: p.flipX ? 'on' : '', onclick: () => { ed(x => { x.params.flipX = !x.params.flipX; }); renderOptions(); } }, 'Flip ↔'),
    el('button', { class: p.flipY ? 'on' : '', onclick: () => { ed(x => { x.params.flipY = !x.params.flipY; }); renderOptions(); } }, 'Flip ↕')));
  if (p.type === 'shape') box.append(el('button', { style: 'margin:4px 0', title: 'Turn this shape into a path so you can move its points and bend its edges', onclick: () => shapeToPath(L) }, '✒ Edit points and curves'));
  commonPlacement(box, L, ed);
}
function commonPlacement(box, L, ed) {
  const p = L.params;
  box.append(check('Mirror to the other side of the car', p.mirror, v => { ed(x => { x.params.mirror = v; }); renderLayers(false); renderOptions(); }));
  if (p.mirror) {
    box.append(seg(null, [['readable', 'Readable'], ['exact', 'Exact mirror']], () => mirrorModeOf(p), v => { ed(x => { x.params.mirrorMode = v; }); renderOptions(); }));
    box.append(el('div', { class: 'note' }, mirrorModeOf(p) === 'readable'
      ? 'Readable: text and logos read the right way round on both sides.'
      : 'Exact mirror: a true reflection, so arrows and swooshes point forward on both sides (text reads backwards).'));
  }
  box.append(seg('Keep inside', [[null, 'Off'], ['panel', 'Panel'], ['part', 'Part']], () => p.clip?.kind ?? null, v => {
    ed(x => { x.params.clip = v ? { kind: v } : null; updateClip(x.params); });
  }));
  box.append(slider('Wrap depth', () => p.depth || 0, (v, fin) => ed(x => { x.params.depth = v < 0.03 ? 0 : v; }, fin), { min: 0, max: 1.5, fmt: v => v < 0.03 ? 'auto' : cm(v) }));
  box.append(el('div', { class: 'note' }, 'Wrap depth: how far around curves it reaches. Lower it if it shows up on parts behind.'));
  box.append(el('div', { class: 'row', style: 'margin-top:10px; flex-wrap:wrap' },
    el('button', { onclick: () => duplicateLayer(L) }, 'Duplicate'),
    el('button', { onclick: () => deleteLayer(L) }, 'Delete'),
    el('button', { onclick: () => { if (pen.drawing) finishPath(); deselectDecal(); } }, 'Done')));
}
function penOptions(box) {
  const L = activePath();
  if (L) return pathOptions(box, L);
  box.append(row('Colour', colorButton(() => S.color, c => { S.color = c; saveSettings(); }, { title: 'Line / fill colour' })));
  box.append(slider('Line width', () => S.pen.width, v => { S.pen.width = v; saveSettings(); }, { min: 0.002, max: 0.6, log: true, fmt: cm }));
  box.append(el('div', { class: 'note' }, 'Click the car to add points. Click and drag to pull out a curve. Click the first point to close it into a filled shape, or press Enter (or click the last point again) to finish a line.'));
  box.append(el('div', { class: 'note' }, 'Afterwards: drag points and handles to adjust, click the outline to add a point, Alt+click a point to switch corner / curve, Delete removes the selected point. Shift+wheel scales, Alt+wheel rotates.'));
}
function pathOptions(box, L) {
  const P = L.params.path, ed = (fn, fin = true) => editLayer(L, x => fn(x.params.path, x.params), fin, true);
  box.append(el('hr'), el('h3', {}, pen.drawing ? 'Drawing a path' : 'Path'));
  if (pen.drawing) box.append(el('div', { class: 'note warn' }, 'Click to add points, drag for curves. Click the first point to close the shape, or press Enter to finish the line.'));
  box.append(check('Line', P.stroke, v => { ed(q => { q.stroke = v; }); renderOptions(); }));
  if (P.stroke) {
    box.append(row('Line colour', colorButton(() => P.strokeColor, (c, fin) => ed(q => { q.strokeColor = c; }, fin))));
    box.append(slider('Width', () => P.width, (v, fin) => ed(q => { q.width = v; }, fin), { min: 0.002, max: 0.6, log: true, fmt: cm }));
  }
  const closed = P.contours.some(c => c.closed);
  box.append(check(closed ? 'Fill' : 'Fill (close the path to fill it)', P.fill, v => { ed(q => { q.fill = v; }); renderOptions(); }));
  if (P.fill) box.append(row('Fill colour', colorButton(() => P.fillColor, (c, fin) => ed(q => { q.fillColor = c; }, fin))));
  box.append(el('div', { class: 'seg', style: 'margin:8px 0' },
    el('button', { onclick: () => { ed(q => { q.contours.forEach(c => { if (c.pts.length > 2) c.closed = !closed; }); if (!closed) { q.fill = true; q.closedOnce = true; } }); renderOptions(); } }, closed ? 'Open the path' : 'Close the path'),
    el('button', { title: 'Project along the surface under the points again (after moving points onto a differently angled panel)', onclick: () => ed((q, p) => refitNormal(p)) }, 'Re-fit to surface')));
  if (pen.sel && S.tool === 'pen') {
    const [ci, pi] = pen.sel, q = P.contours[ci]?.pts[pi];
    if (q) box.append(el('div', { class: 'seg', style: 'margin:4px 0 8px' },
      el('button', { onclick: () => { ed(x => toggleCorner(x.contours[ci], pi)); renderOptions(); } }, q.i || q.o ? 'Make corner' : 'Make curve'),
      el('button', { onclick: () => deletePathPoint(L) }, 'Delete point')));
  }
  if (S.tool !== 'pen') box.append(el('button', { style: 'margin:4px 0', onclick: () => setTool('pen', { keepSelection: true }) }, '✒ Edit points'));
  commonPlacement(box, L, (fn, fin) => editLayer(L, fn, fin, true));
}

// ================================================================================================
// modals
// ================================================================================================
function openModal(...content) { const m = $("#modal"); m.innerHTML = ""; m.append(...content.filter(c => c != null && c !== false)); $('#modalWrap').classList.add('show'); }
function closeModal() { $('#modalWrap').classList.remove('show'); }
function askText(title, initial = '') {
  return new Promise(resolve => {
    const input = el('input', {type:'text', value:initial, style:'width:100%', 'aria-label':title});
    const finish = value => { $('#modal').dataset.locked = ''; closeModal(); resolve(value); };
    const save = el('button', {class:'accent', onclick:() => finish(input.value)}, 'Save');
    openModal(el('h2', {}, title), input, el('div', {class:'actions'},
      el('button', {onclick:() => finish(null)}, 'Cancel'), save));
    $('#modal').dataset.locked = 'true'; input.focus(); input.select();
    input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); finish(input.value); } else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(null); } });
  });
}

$('#modalWrap').addEventListener('pointerdown', e => { if (e.target.id === 'modalWrap' && !$('#modal').dataset.locked) closeModal(); });

function choice(name, value, checked, title, ...kids) {
  const radio = el('input', { type: 'radio', name, value, checked });
  const c = el('label', { class: 'choice' + (checked ? ' on' : '') }, radio, el('div', {}, el('div', {}, title), ...kids));
  radio.addEventListener('change', () => { c.parentElement.querySelectorAll('.choice').forEach(x => x.classList.toggle('on', x.contains(document.querySelector(`input[name=${name}]:checked`)))); });
  return c;
}

async function newDialog() {
  const cars = await api('api/cars');
  if (!cars.length) { toast('No supported mod cars found. This tool needs loose .meb, .vhf and .rcf files.', 'err', 12000); return; }
  const carSel = el('select', { style: 'width:100%' });
  const groups = {};
  for (const c of cars) {
    const g = c.pack || 'Other mod cars';
    if (!groups[g]) { groups[g] = el('optgroup', { label: g }); carSel.append(groups[g]); }
    groups[g].append(el('option', { value: c.id, selected: c.id === (car?.id ?? store.get('car')) }, c.name));
  }
  const livSel = el('select'), projSel = el('select');
  const startColour = el('input', { type: 'color', value: store.get('startColour', '#d9dde3') });
  const fillLists = async () => {
    livSel.innerHTML = ''; projSel.innerHTML = '';
    const [info, projects] = await Promise.all([api('api/info/' + encodeURIComponent(carSel.value)), api('api/projects?car=' + encodeURIComponent(carSel.value))]);
    for (const lv of info.liveries) livSel.append(el('option', { value: lv.id, disabled: !lv.ok }, `${lv.id} · ${lv.name}${lv.ok ? '' : ' (file missing)'}`));
    const firstOk = info.liveries.find(l => l.ok); if (firstOk) livSel.value = firstOk.id;
    for (const p of projects) projSel.append(el('option', { value: p.name }, `${p.name}  (${new Date(p.modified * 1000).toLocaleString()})`));
    projSel.disabled = !projects.length; if (!projects.length) projSel.append(el('option', {}, 'No saved projects for this car yet'));
  };
  carSel.addEventListener('change', fillLists);
  const go = el('button', { class: 'accent' }, 'Start');
  const choices = el('div', {},
    choice('start', 'blank', true, 'Blank car in one colour', el('div', { class: 'row' }, startColour)),
    choice('start', 'livery', false, 'Paint over an existing livery', livSel),
    choice('start', 'project', false, 'Open a saved project', projSel));
  openModal(el('h2', {}, 'Start a livery'), el('label', {}, 'Car'), carSel, choices,
    el('div', { class: 'actions' }, car ? el('button', { onclick: closeModal }, 'Cancel') : null, go));
  await fillLists();
  go.onclick = async () => {
    const mode = choices.querySelector('input[name=start]:checked').value;
    if (projectDirty && !confirm('Discard the unsaved changes in the current livery?')) return;
    closeModal();
    store.set('startColour', startColour.value);
    try {
      if (mode === 'project') await openProject(carSel.value, projSel.value);
      else await startLivery(carSel.value, mode === 'livery' ? +livSel.value : null, startColour.value);
    } catch (e) { toast(e.message, 'err', 8000); await busy(false); }
  };
}

// ================================================================================================
// car / livery / project lifecycle
// ================================================================================================
const project = { name: 'My livery', slot: null };
function setProjectName(n) { project.name = n; $('#projName').textContent = n; document.title = `${n} · AMS2 Livery Editor`; }

async function loadCar(id) {
  if (car?.id === id) return;
  await busy('Loading car…');
  const [data, info] = await Promise.all([api('api/car/' + encodeURIComponent(id)), api('api/info/' + encodeURIComponent(id))]);
  if (car) { scene.remove(car.group); car.meshes.forEach(m => m.geometry.disposeBoundsTree?.() ?? 0); car.meshes.forEach(m => m.geometry.dispose()); car.geo.dispose(); }
  hist.undo.length = hist.redo.length = 0; updateUndoButtons();
  if (engine) { engine.layers = []; gc(); engine.dispose(); allRTs.clear(); paintMat?.dispose(); engine = null; }
  const max = renderer.capabilities.maxTextureSize;
  if (info.width > max || info.height > max) throw new Error(`This car's livery is ${info.width}x${info.height}, your graphics card supports up to ${max}.`);
  car = { id, ...buildCar(data), info, name: data.name };
  const res = clamp(+new URLSearchParams(location.search).get('res') || 1, 0.125, 1);      // ?res=0.5 for weak graphics cards
  engine = new PaintEngine(renderer, car.geo, Math.round(info.width * res), Math.round(info.height * res), car.bounds, car.islands);
  engine.composite.texture.channel = 1; engine.finishRT.texture.channel = 1;
  paintMat = makePaintMaterial();
  for (const m of car.meshes) m.material = m.material.map(x => x || paintMat);
  scene.add(car.group);
  setView('34');
  store.set('car', id);
  $('#carSel').value = id;
  window.ED.car = car;
}

async function startLivery(carId, liveryId, colourHex) {
  await loadCar(carId);
  await busy('Setting up…');
  engine.layers = []; engine.active = null; hist.undo.length = hist.redo.length = 0; gc();
  engine.background = rawColor(colourHex || '#d9dde3'); engine.baseFinish = [1, 1];
  if (liveryId != null) {
    await busy('Loading livery ' + liveryId + '…');
    const blob = await api(`api/livery/${encodeURIComponent(carId)}/${liveryId}.png?full=1`);
    const bmp = await createImageBitmap(blob, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
    const base = engine.addLayer(`Livery ${liveryId}`); reg(base.rt);
    engine.importImage(base, bmp); bmp.close?.();
  }
  const L = engine.addLayer('Paint'); reg(L.rt); engine.active = L;
  setProjectName(liveryId != null ? `${car.name} ${liveryId} edit` : 'My livery'); project.slot = null;
  projectDirty = false; baseSelected = false;
  markDirty(); renderLayers(); renderOptions(); updateUndoButtons();
  await busy(false);
}

// ---- projects ------------------------------------------------------------------------------------
async function layerPNG(L) {
  const buf = engine.readPixels(L.rt, true);
  let any = false; for (let i = 3; i < buf.length; i += 4) if (buf[i]) { any = true; break; }
  if (!any) return null;
  const c = document.createElement('canvas'); c.width = engine.w; c.height = engine.h;
  c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(buf.buffer), engine.w, engine.h), 0, 0);
  const blob = await new Promise(r => c.toBlob(r, 'image/png'));
  return readAsDataURL(blob);
}
async function saveProject(asNew = false) {
  if (!engine) return;
  if (asNew || !project.saved) {
    const n = await askText('Project name', project.name);
    if (!n?.trim()) return;
    setProjectName(n.trim());
  }
  endEdit(); cancelPattern();
  await busy('Saving project…');
  try {
    const layers = [];
    for (const L of engine.layers) {
      const base = { name: L.name, kind: L.kind, visible: L.visible, opacity: L.opacity, lock: L.lock, finishOnly: L.finishOnly, finish: L.finish };
      layers.push(L.kind === 'paint' ? { ...base, png: await layerPNG(L) } : { ...base, params: L.params });
    }
    const doc = { version: 1, car: car.id, name: project.name, width: engine.w, height: engine.h, slot: project.slot,
                  background: hex(engine.background), baseFinish: engine.baseFinish, layers, active: engine.layers.indexOf(engine.active) };
    await api(`api/project?car=${encodeURIComponent(car.id)}&name=${encodeURIComponent(project.name)}`, { method: 'POST', body: JSON.stringify(doc) });
    project.saved = true; projectDirty = false;
    toast(`Project "${project.name}" saved`, 'ok', 2500);
  } catch (e) { toast('Could not save the project: ' + e.message, 'err', 8000); }
  await busy(false);
}
async function openProject(carId, name) {
  await loadCar(carId);
  await busy('Opening project…');
  const doc = await api(`api/project?car=${encodeURIComponent(carId)}&name=${encodeURIComponent(name)}`);
  engine.layers = []; engine.active = null; hist.undo.length = hist.redo.length = 0; gc();
  engine.background = rawColor(doc.background || '#d9dde3'); engine.baseFinish = doc.baseFinish || [1, 1];
  for (const d of doc.layers) {
    let L;
    if (d.kind === 'paint') {
      L = engine.addLayer(d.name); reg(L.rt);
      if (d.png) { const bmp = await createImageBitmap(await (await fetch(d.png)).blob(), { premultiplyAlpha: 'none', colorSpaceConversion: 'none' }); engine.importImage(L, bmp); bmp.close?.(); }
    } else { L = engine.addDecalLayer(d.name); L.params = d.params; await refreshDecal(L, true); }
    Object.assign(L, { visible: d.visible, opacity: d.opacity, lock: !!d.lock, finishOnly: !!d.finishOnly, finish: d.finish || null });
  }
  engine.active = engine.layers[doc.active] || engine.layers.at(-1) || null;
  setProjectName(doc.name); project.slot = doc.slot ?? null; project.saved = true; projectDirty = false;
  markDirty(); renderLayers(); renderOptions(); updateUndoButtons();
  await busy(false);
}
async function openProjectDialog() {
  const projects = await api('api/projects');
  if (!projects.length) return toast('No saved projects yet');
  const list = el('div', {}, projects.map(p => el('label', { class: 'choice' }, el('input', { type: 'radio', name: 'proj', value: JSON.stringify([p.car, p.name]) }),
    el('div', {}, el('div', {}, p.name), el('div', { class: 'note' }, `${p.carName} · ${new Date(p.modified * 1000).toLocaleString()}`)))));
  const ok = el('button', { class: 'accent', onclick: async () => {
    const v = list.querySelector('input:checked'); if (!v) return;
    if (projectDirty && !confirm('Discard the unsaved changes in the current livery?')) return;
    closeModal(); const [c, n] = JSON.parse(v.value);
    try { await openProject(c, n); } catch (e) { toast(e.message, 'err', 8000); await busy(false); }
  } }, 'Open');
  openModal(el('h2', {}, 'Open a project'), list, el('div', { class: 'actions' }, el('button', { onclick: closeModal }, 'Cancel'), ok));
}

// ---- export ------------------------------------------------------------------------------------
const customFinish = () => [engine.baseFinish, ...engine.layers.filter(l => l.visible && l.finish).map(l => l.finish)].some(f => f[0] < 0.995 || f[1] < 0.995);
async function downloadPng() {
  endEdit(); cancelPattern();
  await busy('Rendering the livery…');
  const buf = engine.exportPixels();
  const c = document.createElement('canvas'); c.width = engine.w; c.height = engine.h;
  c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(buf.buffer), engine.w, engine.h), 0, 0);
  const blob = await new Promise(r => c.toBlob(r, 'image/png'));
  const a = el('a', { href: URL.createObjectURL(blob), download: `${project.name}.png` }); a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  await busy(false);
}
async function saveToGameDialog() {
  if (!engine) return;
  endEdit(); cancelPattern();
  const info = await api('api/info/' + encodeURIComponent(car.id));
  car.info = info;
  const name = el('input', { type: 'text', value: project.name, style: 'width:100%' });
  const slotSel = el('select', {}, info.liveries.map(l => el('option', { value: l.id, selected: l.id === project.slot }, `${l.id} · ${l.name}${l.ours ? '  (made with this editor)' : ''}`)));
  const warn = el('div', { class: 'note warn' });
  const checkWarn = () => { const l = info.liveries.find(x => x.id === +slotSel.value); warn.textContent = l && !l.ours ? 'This is one of the car\'s own liveries. It will be replaced (the original is backed up).' : ''; };
  slotSel.addEventListener('change', checkWarn); checkWarn();
  const hasSlot = project.slot != null && info.liveries.some(l => l.id === project.slot);
  const choices = el('div', {},
    choice('slot', 'new', !hasSlot, `Add as a new livery (number ${info.next})`),
    choice('slot', 'update', hasSlot, 'Replace an existing livery', slotSel, warn));
  const alsoSave = el('input', { type: 'checkbox', checked: true });
  const fin = customFinish();
  const finNote = el('div', { class: 'note' + (fin && !info.finish.supported ? ' warn' : '') },
    !fin ? 'Finish: standard gloss everywhere.' : info.finish.supported ? 'Finish: your gloss/matte settings are saved too.' : `Finish: ${info.finish.reason}. Gloss/matte changes won't show in game on this car.`);
  const go = el('button', { class: 'accent' }, 'Save to game');
  openModal(el('h2', {}, 'Save to Automobilista 2'), el('label', {}, 'Name in the livery list'), name, choices, finNote,
    el('label', { class: 'check' }, alsoSave, 'Also save this project (so you can keep editing it)'),
    el('div', { class: 'note' }, 'Close AMS2 before saving to the game. Every file it changes is backed up in "_livery_tool_backups" in the game folder.'),
    el('div', { class: 'actions' }, el('button', { onclick: closeModal }, 'Cancel'), go));
  go.onclick = async () => {
    const mode = choices.querySelector('input[name=slot]:checked').value;
    const slot = mode === 'update' ? +slotSel.value : null;
    const nm = name.value.trim() || project.name;
    closeModal();
    try {
      await busy('Rendering the livery…');
      const px = engine.exportPixels();
      const spec = fin && info.finish.supported ? engine.exportFinish() : null;
      await busy('Writing to the game (this takes a few seconds)…');
      const body = spec ? new Blob([px, spec]) : new Blob([px]);
      const q = new URLSearchParams({ car: car.id, name: nm, width: engine.w, height: engine.h, finish: spec ? 1 : 0 });
      if (slot != null) q.set('slot', slot);
      const res = await api('api/install?' + q, { method: 'POST', body });
      project.slot = res.slot;
      if (nm !== project.name) setProjectName(nm);
      let picture = null, pictureNote = null;
      try {                                                        // the picture shown in the game's livery list
        await busy('Rendering the picture for the livery list…');
        const shot = renderPreview();
        await api(`api/preview?car=${encodeURIComponent(car.id)}&slot=${res.slot}&width=${shot.w}&height=${shot.h}`, { method: 'POST', body: new Blob([shot.px]) });
        picture = shot.url;
      } catch (err) { pictureNote = 'The livery list picture could not be made: ' + err.message; }
      await busy(false);
      if (alsoSave.checked) { project.saved = true; await saveProject(); }
      openModal(el('h2', {}, `Saved as livery ${res.slot}`),
        el('p', {}, `"${res.name}" is now livery ${res.slot} on the ${car.name}.`),
        picture ? el('img', { src: picture, alt: 'Livery list picture', style: 'width:100%;border-radius:6px;background:#0b0c0e;margin:4px 0' }) : null,
        pictureNote ? el('p', { class: 'note warn' }, pictureNote) : null,
        res.finish ? el('p', { class: 'note' }, 'Finish map saved too.') : null,
        res.note ? el('p', { class: 'note warn' }, res.note) : null,
        el('p', { class: 'note' }, 'Restart AMS2 if it is running, then pick it in the livery list. Friends need the same files at the same number to see it online.'),
        el('div', { class: 'actions' }, el('button', { class: 'accent', onclick: closeModal }, 'OK')));
    } catch (e) { await busy(false); toast('Could not save: ' + e.message, 'err', 10000); }
  };
}
async function importLayer() {
  pickFile(async f => {
    const bmp = await createImageBitmap(f, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
    if (Math.abs(bmp.width / bmp.height - engine.w / engine.h) > 0.01) toast(`Note: the image is ${bmp.width}x${bmp.height}, the livery is ${engine.w}x${engine.h}. It was stretched to fit.`, '', 7000);
    const L = addPaintLayer(f.name.replace(/\.[^.]+$/, ''));
    engine.importImage(L, bmp); bmp.close?.();
    markDirty(); renderLayers(); renderOptions();
  }, 'image/png,image/jpeg,image/webp');
}

// ---- the picture the game shows in its livery list: 2048 x 768, front-right three-quarter view -------
const TONE_FRAG = /* glsl */`uniform sampler2D src; varying vec2 vUv;
  vec3 neutral(vec3 color) {                                    // Khronos PBR Neutral, as the editor view uses
    const float start = 0.76, desat = 0.15;
    float x = min(color.r, min(color.g, color.b));
    float offset = x < 0.08 ? x - 6.25 * x * x : 0.04;
    color -= offset;
    float peak = max(color.r, max(color.g, color.b));
    if (peak < start) return color;
    float d = 1.0 - start, newPeak = 1.0 - d * d / (peak + d - start);
    color *= newPeak / peak;
    float g = 1.0 - 1.0 / (desat * (peak - newPeak) + 1.0);
    return mix(color, vec3(newPeak), g);
  }
  vec3 srgb(vec3 c) { return mix(pow(c, vec3(0.41666)) * 1.055 - vec3(0.055), c * 12.92, vec3(lessThanEqual(c, vec3(0.0031308)))); }
  void main() {
    vec4 c = texture2D(src, vUv);
    vec3 rgb = c.a > 0.001 ? c.rgb / c.a : vec3(0.0);
    gl_FragColor = vec4(srgb(clamp(neutral(rgb), 0.0, 1.0)), clamp(c.a, 0.0, 1.0));
  }`;
function renderPreview(W = 2048, H = 768) {
  engine.render(); engine.dilateComposite(); engine.renderFinish();
  car.group.updateMatrixWorld(true);
  const cam = new THREE.PerspectiveCamera(24, W / H, 0.05, 200);
  const c = new THREE.Box3().setFromObject(car.group).getCenter(new THREE.Vector3());
  cam.position.copy(c).addScaledVector(new THREE.Vector3(0.6, 0.1, -0.78).normalize(), 11);    // front right, just above the roof
  cam.lookAt(c); cam.updateMatrixWorld(); cam.updateProjectionMatrix();
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  const v = new THREE.Vector3();
  for (const m of car.meshes) {                                  // fit the car to the picture
    const pos = m.geometry.attributes.position, step = Math.max(1, Math.floor(pos.count / 3000));
    for (let i = 0; i < pos.count; i += step) {
      v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld).project(cam);
      x0 = Math.min(x0, v.x); x1 = Math.max(x1, v.x); y0 = Math.min(y0, v.y); y1 = Math.max(y1, v.y);
    }
  }
  const zoom = 0.97 / Math.max((x1 - x0) / 2, (y1 - y0) / 2);
  cam.zoom = zoom;
  cam.setViewOffset(W, H, (x0 + x1) / 2 * zoom * W / 2, -(y0 + y1) / 2 * zoom * H / 2, W, H);
  cam.updateProjectionMatrix();
  const hdr = renderer.extensions.has('EXT_color_buffer_float');
  const rt = new THREE.WebGLRenderTarget(W, H, { samples: 4, type: hdr ? THREE.HalfFloatType : THREE.UnsignedByteType });
  const out = new THREE.WebGLRenderTarget(W, H, { type: THREE.UnsignedByteType, depthBuffer: false });
  const keep = { bg: scene.background, floor: floor.visible, rings: rings.map(r => r.visible), clear: renderer.getClearColor(new THREE.Color()), alpha: renderer.getClearAlpha() };
  scene.background = null; floor.visible = false; rings.forEach(r => { r.visible = false; });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }', fragmentShader: TONE_FRAG,
    uniforms: { src: { value: rt.texture } }, depthTest: false, depthWrite: false }));
  const qs = new THREE.Scene(); qs.add(quad);
  const buf = new Uint8Array(W * H * 4);
  try {
    renderer.setRenderTarget(rt); renderer.setClearColor(0x000000, 0); renderer.clear(); renderer.render(scene, cam);
    renderer.setRenderTarget(out); renderer.render(qs, new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1));
    renderer.readRenderTargetPixels(out, 0, 0, W, H, buf);
  } finally {
    renderer.setRenderTarget(null);
    scene.background = keep.bg; floor.visible = keep.floor; rings.forEach((r, i) => { r.visible = keep.rings[i]; });
    renderer.setClearColor(keep.clear, keep.alpha);
    [rt, out, quad.geometry, quad.material].forEach(x => x.dispose());
  }
  const px = new Uint8Array(buf.length), row = W * 4;           // GL rows run bottom-up: flip to image order
  for (let y = 0; y < H; y++) px.set(buf.subarray((H - 1 - y) * row, (H - y) * row), y * row);
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  cv.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(px.buffer), W, H), 0, 0);
  return { px, w: W, h: H, url: cv.toDataURL('image/png') };
}

// ---- liveries a mod update took out of a car's list ---------------------------------------------------
async function checkMissing() {
  let list;
  try { list = await api('api/missing'); } catch { return; }
  const b = $('#banner');
  if (!list.length) { b.classList.remove('show'); return; }
  b.innerHTML = '';
  const names = list.map(e => `"${e.name}" (${e.carName})`).join(', ');
  b.append(el('span', {}, `${list.length === 1 ? 'A livery you made is' : `${list.length} liveries you made are`} no longer in the game's list, probably after a mod update: ${names}.`),
    el('button', { class: 'accent', onclick: () => restoreMissing(list) }, 'Put back'),
    el('button', { title: 'Hide', onclick: () => b.classList.remove('show') }, '✕'));
  b.classList.add('show');
}
async function restoreMissing(list) {
  await busy('Putting your liveries back…');
  try {
    const res = await api('api/restore', { method: 'POST', body: JSON.stringify(list) });
    $('#banner').classList.remove('show');
    await busy(false);
    openModal(el('h2', {}, 'Liveries put back'),
      el('ul', {}, res.restored.map(r => el('li', {}, `${r.carName}: "${r.name}" is livery ${r.slot}${r.old !== r.slot ? ` (it was ${r.old})` : ''}`))),
      res.skipped.length ? el('p', { class: 'note warn' }, 'Not put back: ' + res.skipped.map(x => `"${x.name}" (${x.reason})`).join(', ')) : null,
      el('p', { class: 'note' }, 'Restart AMS2 if it is running. If a number changed, friends need the livery at the new number too.'),
      el('div', { class: 'actions' }, el('button', { class: 'accent', onclick: closeModal }, 'OK')));
  } catch (e) { await busy(false); toast('Could not put them back: ' + e.message, 'err', 8000); }
}

// ---- custom shape editor ------------------------------------------------------------------------
function shapeEditor(existing) {
  const SZ = 360, pad = 20;
  const pts = existing ? existing.pts.map(p => [...p]) : [];
  const canvas = el('canvas', { width: SZ, height: SZ, class: 'shapeEd' });
  const name = el('input', { type: 'text', value: existing?.name || 'My shape', style: 'width:100%' });
  const snapBox = el('input', { type: 'checkbox', checked: true }), smoothBox = el('input', { type: 'checkbox', checked: !!existing?.smooth });
  const g = canvas.getContext('2d');
  const toC = p => [pad + p[0] * (SZ - 2 * pad), pad + p[1] * (SZ - 2 * pad)];
  const fromC = (x, y) => { let u = (x - pad) / (SZ - 2 * pad), v = (y - pad) / (SZ - 2 * pad);
    if (snapBox.checked) { u = Math.round(u * 16) / 16; v = Math.round(v * 16) / 16; } return [clamp(u, 0, 1), clamp(v, 0, 1)]; };
  const draw = () => {
    g.clearRect(0, 0, SZ, SZ);
    g.strokeStyle = 'rgba(255,255,255,.08)'; g.lineWidth = 1;
    for (let i = 0; i <= 16; i++) { const a = pad + i * (SZ - 2 * pad) / 16; g.beginPath(); g.moveTo(a, pad); g.lineTo(a, SZ - pad); g.moveTo(pad, a); g.lineTo(SZ - pad, a); g.stroke(); }
    if (pts.length > 1) {
      g.save(); g.translate(pad, pad); g.scale(SZ - 2 * pad, SZ - 2 * pad); g.beginPath();
      if (pts.length > 2) ST.drawCustom(g, { pts, smooth: smoothBox.checked }); else { g.moveTo(...pts[0]); g.lineTo(...pts[1]); }
      g.restore();
      g.fillStyle = 'rgba(255,106,26,.45)'; g.fill(); g.strokeStyle = '#ff6a1a'; g.lineWidth = 2; g.stroke();
    }
    pts.forEach((p, i) => { const [x, y] = toC(p); g.beginPath(); g.arc(x, y, i === 0 ? 6 : 5, 0, Math.PI * 2); g.fillStyle = i === 0 ? '#ff6a1a' : '#fff'; g.fill(); });
  };
  let dragI = -1;
  const near = (x, y) => pts.findIndex(p => { const [px, py] = toC(p); return Math.hypot(px - x, py - y) < 9; });
  canvas.addEventListener('pointerdown', e => {
    const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, i = near(x, y);
    if (e.button === 2 || e.altKey) { if (i >= 0) pts.splice(i, 1); draw(); return; }
    if (i >= 0) dragI = i; else { pts.push(fromC(x, y)); dragI = pts.length - 1; }
    canvas.setPointerCapture(e.pointerId); draw();
  });
  canvas.addEventListener('pointermove', e => { if (dragI < 0) return; const r = canvas.getBoundingClientRect(); pts[dragI] = fromC(e.clientX - r.left, e.clientY - r.top); draw(); });
  canvas.addEventListener('pointerup', () => { dragI = -1; });
  canvas.addEventListener('contextmenu', e => e.preventDefault());
  smoothBox.addEventListener('change', draw);
  const save = el('button', { class: 'accent', onclick: () => {
    if (pts.length < 3) return toast('A shape needs at least 3 points');
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const x0 = Math.min(...xs), y0 = Math.min(...ys), sx = Math.max(...xs) - x0 || 1, sy = Math.max(...ys) - y0 || 1;
    const norm = pts.map(([x, y]) => [(x - x0) / sx, (y - y0) / sy]);
    const list = customShapes().filter(s => s.name !== (existing?.name ?? '\0') && s.name !== name.value.trim());
    const shape = { name: name.value.trim() || 'My shape', pts: norm, smooth: smoothBox.checked };
    store.set('customShapes', [...list, shape]);
    S.shape.shape = 'custom'; S.shape.custom = { pts: norm, smooth: shape.smooth }; S.shape.customName = shape.name; S.shape.aspect = sx / sy; saveSettings();
    closeModal(); setTool('shape');
  } }, 'Save shape');
  const del = existing ? el('button', { onclick: () => { store.set('customShapes', customShapes().filter(s => s.name !== existing.name)); closeModal(); renderOptions(); } }, 'Delete') : null;
  openModal(el('h2', {}, existing ? 'Edit shape' : 'Draw a custom shape'),
    el('div', { class: 'note' }, 'Click to add points, drag to move them, right-click to remove one.'),
    canvas,
    el('div', { style: 'display:flex;gap:18px' }, el('label', { class: 'check' }, snapBox, 'Snap to grid'), el('label', { class: 'check' }, smoothBox, 'Smooth curves')),
    el('label', {}, 'Name'), name,
    el('div', { class: 'actions' }, del, el('button', { onclick: () => { pts.length = 0; draw(); } }, 'Clear'), el('button', { onclick: closeModal }, 'Cancel'), save));
  draw();
}

// camera presets (world space: the car's front is -Z, its left side is -X)
const VIEWS = { '34': ['3/4', [-0.62, 0.3, -0.72]], left: ['Left', [-1, 0.12, 0]], right: ['Right', [1, 0.12, 0]], front: ['Front', [0, 0.18, -1]],
                rear: ['Rear', [0, 0.25, 1]], top: ['Top', [0, 1, 0.0001]], '34r': ['3/4 rear', [0.62, 0.35, 0.72]] };
function setView(name) {
  if (!car) return;
  const box = new THREE.Box3().setFromObject(car.group), c = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
  const [, dir] = VIEWS[name];
  const d = new THREE.Vector3(...dir).normalize();
  const extent = name === 'left' || name === 'right' ? Math.max(size.z, size.y * camera.aspect) : name === 'top' ? Math.max(size.z, size.x * camera.aspect) : Math.hypot(size.x, size.z);
  const dist = extent / 2 / Math.tan(camera.fov * Math.PI / 360) / Math.min(1, camera.aspect) * 1.12;
  controls.target.set(c.x, c.y * (name === 'top' ? 1 : 0.9), c.z);
  camera.position.copy(controls.target).addScaledVector(d, Math.max(dist, 2));
  controls.update();
}
$('#views').append(...Object.entries(VIEWS).map(([k, [label]]) => el('button', { onclick: () => setView(k), title: 'Camera: ' + label }, label)));

// ================================================================================================
// top bar + layer buttons
// ================================================================================================
$('#undoBtn').onclick = undo; $('#redoBtn').onclick = redo;
$('#symBtn').onclick = toggleSymmetry;
$('#newBtn').onclick = () => newDialog();
$('#saveGameBtn').onclick = () => saveToGameDialog();
$('#addLayerBtn').onclick = () => { if (engine) { addPaintLayer('Paint'); renderOptions(); } };
$('#dupLayerBtn').onclick = () => duplicateLayer();
$('#mergeLayerBtn').onclick = () => mergeDown();
$('#upLayerBtn').onclick = () => moveLayer(active(), 1);
$('#downLayerBtn').onclick = () => moveLayer(active(), -1);
$('#delLayerBtn').onclick = () => deleteLayer();
$('#fileBtn').onclick = e => { e.stopPropagation(); $('#fileMenu').classList.toggle('open'); };
addEventListener('click', () => $('#fileMenu').classList.remove('open'));
$('#fileMenu .dd').addEventListener('click', e => {
  const act = e.target.dataset.act; if (!act || !engine && act !== 'viewer') return;
  ({ saveProject: () => saveProject(), saveProjectAs: () => saveProject(true), openProject: openProjectDialog, importLayer, downloadPng,
     viewer: () => open('viewer', '_blank') })[act]?.();
});
$('#carSel').addEventListener('change', async e => {
  const id = e.target.value;
  if (projectDirty && !confirm('Switch car? Unsaved changes to this livery will be lost (save the project first if you want to keep them).')) { e.target.value = car.id; return; }
  try { await startLivery(id, null, hex(engine?.background ?? '#d9dde3')); } catch (err) { toast(err.message, 'err', 8000); await busy(false); }
});
addEventListener('beforeunload', e => { if (projectDirty) { e.preventDefault(); e.returnValue = ''; } });

// ================================================================================================
// render loop
// ================================================================================================
let lastFinish = 0;
renderer.setAnimationLoop(() => {
  controls.update();
  if (engine) {
    const now = performance.now();
    if (needs.composite) { engine.render(); needs.composite = false; needs.dilate = now; }
    if (needs.dilate && !drag && now - needs.dilate > 150) { engine.dilateComposite(); needs.dilate = 0; }
    if (needs.finish && !drag && now - lastFinish > 120) { engine.renderFinish(); needs.finish = false; lastFinish = now; }
  }
  updateCursor();
  renderer.render(scene, camera);
  if (car) { drawHandles(); drawPen(); }
});

// ================================================================================================
// start
// ================================================================================================
window.ED = { S, get engine() { return engine; }, car: null, pick, pickObject, setTool, setActive, createDecal, refreshDecal, startLivery, openProject,
              saveProject, undo, redo, applyPattern, previewPattern, toScreen, decalFrames, exportPixels: () => engine.exportPixels(),
              customFinish, hist, toggleSymmetry, renderOptions, renderLayers, setColour, deleteLayer, mergeDown, rasterizeLayer, layersChange, pushHistory,
              editLayer, endEdit, M, project, newDialog, saveToGameDialog, markDirty: () => markDirty(), renderer, camera, controls, setView,
              renderPreview, pen, pat, activePath, finishPath, shapeToPath, checkMissing, gradStops, addPaintLayer, cancelPattern };
ST.loadGoogleFonts();
buildToolbar();
$('#symBtn').classList.toggle('on', S.symmetry);
$('#hint').textContent = HINTS[S.tool] || '';
updateUndoButtons();
(async () => {
  try {
    const cars = await api('api/cars');
  if (!cars.length) { toast('No supported mod cars found. This tool needs loose .meb, .vhf and .rcf files.', 'err', 12000); return; }
    const sel = $('#carSel'), groups = {};
    for (const c of cars) {
      const g = c.pack || 'Other mod cars';
      if (!groups[g]) { groups[g] = el('optgroup', { label: g }); sel.append(groups[g]); }
      groups[g].append(el('option', { value: c.id }, c.name));
    }
    if (!cars.length) { toast('No mod cars with 3D models were found in your game folder.', 'err', 20000); return; }
    const start = cars.find(c => c.id === store.get('car')) || cars[0];
    await startLivery(start.id, null, store.get('startColour', '#d9dde3'));
    projectDirty = false;
    window.editorReady = true;
    if (!new URLSearchParams(location.search).has('nodialog')) newDialog();
    checkMissing();
  } catch (e) { await busy(false); toast('Could not start: ' + e.message, 'err', 20000); window.editorError = e.message; }
})();

window.paddockDesignerCanLeave = () => !projectDirty || confirm('Leave the designer and discard unsaved changes?');
