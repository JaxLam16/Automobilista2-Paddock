// GPU paint engine: every tool draws the car's paint triangles in texture (UV) space, so a fragment
// knows its own 3D position, normal, panel (UV island) and part. Brushes are spheres in 3D, stamps are
// planar projections, fills/gradients/patterns are functions of 3D position. Paint layers are
// premultiplied RGBA render targets; decal layers (text, shapes, images) stay editable and are
// projected on the fly. An overlay target holds the in-progress operation until it is committed.
import * as THREE from 'three';

const MAXD = 48;

/** Colours are written to the livery exactly as picked (sRGB values), so no colour management here. */
export function rawColor(c, out = new THREE.Color()) {
  if (c instanceof THREE.Color) return out.copy(c);
  if (Array.isArray(c)) return out.setRGB(c[0], c[1], c[2], THREE.LinearSRGBColorSpace);
  if (typeof c === 'number') return out.setHex(c, THREE.LinearSRGBColorSpace);
  return out.setStyle(c, THREE.LinearSRGBColorSpace);
}

const UV_VERT = /* glsl */`
  #define MAXD ${MAXD}
  attribute vec2 luv; attribute float island; attribute float part; attribute vec4 tri;
  uniform int cullMode; uniform vec4 cullSphere; uniform vec4 dabs[MAXD]; uniform int dabCount;
  varying vec3 vPos; varying vec3 vNrm; varying float vIsl; varying float vPart; varying vec2 vUv;
  void main() {
    vPos = position; vNrm = normal; vIsl = island; vPart = part; vUv = luv;
    bool keep = true;
    if (cullMode == 1) {
      keep = false;
      for (int i = 0; i < MAXD; i++) { if (i >= dabCount) break; if (distance(tri.xyz, dabs[i].xyz) <= dabs[i].w + tri.w) { keep = true; break; } }
    } else if (cullMode == 2) keep = distance(tri.xyz, cullSphere.xyz) <= cullSphere.w + tri.w;
    gl_Position = keep ? vec4(luv * 2.0 - 1.0, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
  }`;

const FILTER = /* glsl */`
  uniform float filterIsland; uniform float filterPart; uniform bool useMask; uniform sampler2D islandMask; uniform vec2 maskSize;
  varying vec3 vPos; varying vec3 vNrm; varying float vIsl; varying float vPart; varying vec2 vUv;
  bool passFilter() {
    if (useMask) {                                                   // a set of panels: one texel per panel
      float i = floor(vIsl + 0.5);
      vec2 at = vec2(mod(i, maskSize.x) + 0.5, floor(i / maskSize.x) + 0.5) / maskSize;
      if (texture2D(islandMask, at).r < 0.5) return false;
    }
    if (filterIsland >= 0.0 && abs(vIsl - filterIsland) > 0.5) return false;
    if (filterPart >= 0.0 && abs(vPart - filterPart) > 0.5) return false;
    return true;
  }`;

// dabs[i] = (centre, radius), dabN[i] = (normal, island or -1)
const DAB_FRAG = /* glsl */`
  #define MAXD ${MAXD}
  ${FILTER}
  uniform vec4 dabs[MAXD]; uniform vec4 dabN[MAXD]; uniform int dabCount; uniform float hardness;
  uniform vec3 color; uniform bool protect;
  void main() {
    if (!passFilter()) discard;
    vec3 n = normalize(vNrm); float a = 0.0;
    for (int i = 0; i < MAXD; i++) {
      if (i >= dabCount) break;
      vec4 d = dabs[i]; vec4 dn = dabN[i];
      if (protect && dn.w >= 0.0 && abs(vIsl - dn.w) > 0.5) continue;
      if (dot(n, dn.xyz) < 0.05) continue;
      float dist = distance(vPos, d.xyz);
      if (dist >= d.w) continue;
      a = max(a, 1.0 - smoothstep(d.w * hardness, d.w, dist));
    }
    if (a <= 0.0) discard;
    gl_FragColor = vec4(color * a, a);
  }`;

const DECAL_FRAG = /* glsl */`
  ${FILTER}
  uniform sampler2D decalTex; uniform vec3 dC; uniform vec3 dR; uniform vec3 dU; uniform vec3 dN; uniform vec2 dSize;
  uniform float depth; uniform float opacity; uniform bool tint; uniform vec3 color;
  void main() {
    if (!passFilter()) discard;
    vec3 rel = vPos - dC;
    float a = dot(rel, dR) / dSize.x + 0.5, b = 0.5 - dot(rel, dU) / dSize.y;
    if (a < 0.0 || a > 1.0 || b < 0.0 || b > 1.0) discard;
    if (abs(dot(rel, dN)) > depth || dot(normalize(vNrm), dN) < 0.1) discard;
    vec4 c = texture2D(decalTex, vec2(a, b));
    if (tint) c.rgb = color;
    float al = c.a * opacity;
    if (al <= 0.002) discard;
    gl_FragColor = vec4(c.rgb * al, al);
  }`;

const FILL_FRAG = /* glsl */`
  ${FILTER}
  uniform vec4 color;
  void main() { if (!passFilter()) discard; gl_FragColor = vec4(color.rgb * color.a, color.a); }`;

export const MAX_STOPS = 16;
const GRAD_FRAG = /* glsl */`
  #define MAXS ${16}
  ${FILTER}
  uniform vec3 gA; uniform vec3 gB; uniform int gType; uniform vec4 gCol[MAXS]; uniform float gPos[MAXS]; uniform int gN;
  uniform int gBlend; uniform float gRepeat;
  void main() {
    if (!passFilter()) discard;
    vec3 ab = gB - gA; float L2 = max(dot(ab, ab), 1e-8), t;
    if (gType == 1) t = distance(vPos, gA) / sqrt(L2);                // radial
    else if (gType == 2) t = abs(dot(vPos - gA, ab)) / L2;            // reflected
    else t = dot(vPos - gA, ab) / L2;                                 // linear
    t = clamp(t, 0.0, 1.0);
    if (gRepeat > 1.0) { t *= gRepeat; t = t >= gRepeat - 1e-4 ? 1.0 : fract(t); }
    vec4 c = gCol[0];
    if (t >= gPos[gN - 1]) c = gCol[gN - 1];
    else if (t > gPos[0]) {
      for (int i = 1; i < MAXS; i++) {
        if (i >= gN) break;
        if (t <= gPos[i]) {
          float f = clamp((t - gPos[i - 1]) / max(gPos[i] - gPos[i - 1], 1e-5), 0.0, 1.0);
          if (gBlend == 1) f = smoothstep(0.0, 1.0, f); else if (gBlend == 2) f = 0.0;
          c = mix(gCol[i - 1], gCol[i], f);
          break;
        }
      }
    }
    if (c.a <= 0.002) discard;
    gl_FragColor = vec4(c.rgb * c.a, c.a);
  }`;

export const PATTERNS = [
  'Dots', 'Squares', 'Triangles', 'Hexagons', 'Stripes', 'Chevrons', 'Checker', 'Camo', 'Shards',
  'Carbon fibre', 'Forged carbon', 'Brushed metal', 'Honeycomb mesh', 'Grid', 'Waves', 'Digital camo',
];

const PATTERN_FRAG = /* glsl */`
  ${FILTER}
  uniform int pType; uniform int pProj; uniform float pAngle; uniform float pSpacing; uniform float pSize;
  uniform float pSpread; uniform float pDrop; uniform float pSeed; uniform vec3 pC1; uniform vec3 pC2; uniform bool pTwo;
  uniform int pFadeType; uniform vec3 fA; uniform vec3 fB; uniform float pFadeStart; uniform float pFadeEnd; uniform float pFadeCurve;
  uniform int pFadeFx; uniform float pAlpha;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7)) + pSeed * 17.13) * 43758.5453); }
  vec2 hash2(vec2 p) { return vec2(hash(p), hash(p + 19.19)); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
  }
  float fbm(vec2 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 4; i++) { s += a * noise(p); p *= 2.03; a *= 0.5; } return s; }
  vec2 proj() {
    vec3 n = abs(normalize(vNrm)); int m = pProj;
    if (m == 0) m = (n.x >= n.y && n.x >= n.z) ? 1 : (n.y >= n.z ? 2 : 3);
    if (m == 1) return vec2(vPos.z, vPos.y);
    if (m == 2) return vec2(vPos.z, vPos.x);
    return vec2(vPos.x, vPos.y);
  }
  // 1 where the pattern is full, 0 where it has faded out: along fA -> fB, or outwards from fA (radial)
  float fadeAmt() {
    if (pFadeType == 0) return 1.0;
    vec3 ab = fB - fA; float L2 = max(dot(ab, ab), 1e-8);
    float t = pFadeType == 2 ? distance(vPos, fA) / sqrt(L2) : dot(vPos - fA, ab) / L2;
    float f = 1.0 - smoothstep(pFadeStart, max(pFadeEnd, pFadeStart + 0.001), clamp(t, 0.0, 1.0));
    return pow(f, pFadeCurve);
  }
  bool fxOn(int b) { return mod(floor(float(pFadeFx) / float(b)), 2.0) >= 1.0; }   // 1 size, 2 density, 4 opacity
  mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }
  float sdTri(vec2 p, float r) { const float k = 1.7320508; p.x = abs(p.x) - r; p.y = p.y + r / k;
    if (p.x + k * p.y > 0.0) p = vec2(p.x - k * p.y, -k * p.x - p.y) / 2.0; p.x -= clamp(p.x, -2.0 * r, 0.0); return -length(p) * sign(p.y); }
  float sdHex(vec2 p, float r) { const vec3 k = vec3(-0.866025404, 0.5, 0.577350269); p = abs(p);
    p -= 2.0 * min(dot(k.xy, p), 0.0) * k.xy; p -= vec2(clamp(p.x, -k.z * r, k.z * r), r); return length(p) * sign(p.y); }
  void main() {
    if (!passFilter()) discard;
    vec2 q = rot(pAngle) * proj() / pSpacing;
    float fadeRaw = fadeAmt();
    float fade = fxOn(1) ? fadeRaw : 1.0, fg = fxOn(2) ? fadeRaw : 1.0, fo = fxOn(4) ? fadeRaw : 1.0;
    float aa = max(length(fwidth(q)), 1e-4);
    vec3 col = pC1; float a = 0.0;
    vec2 cell = floor(q), f = fract(q) - 0.5;
    float h = hash(cell + 3.7);
    bool dropped = hash(cell + 7.1) >= (1.0 - pDrop) * fg;          // gaps, and fewer shapes where it fades
    f -= (hash2(cell) - 0.5) * pSpread;
    float s = pSize * fade * (1.0 - pSpread * 0.6 * h);
    if (pTwo && h > 0.5) col = pC2;
    if (pType == 0) a = 1.0 - smoothstep(-aa, aa, length(f) - s * 0.5);                        // dots
    else if (pType == 1) a = 1.0 - smoothstep(-aa, aa, max(abs(f.x), abs(f.y)) - s * 0.5);    // squares
    else if (pType == 2) a = 1.0 - smoothstep(-aa, aa, sdTri(rot(h * 6.283 * pSpread) * f, s * 0.42)); // triangles
    else if (pType == 3) a = 1.0 - smoothstep(-aa, aa, sdHex(f, s * 0.45));                  // hexagons
    else if (pType == 4) { float d = abs(fract(q.x) - 0.5) - pSize * 0.5 * fade; a = 1.0 - smoothstep(-aa, aa, d); col = pC1; dropped = false; } // stripes
    else if (pType == 5) { float d = abs(fract(q.x + abs(fract(q.y) - 0.5)) - 0.5) - pSize * 0.5 * fade; a = 1.0 - smoothstep(-aa, aa, d); col = pC1; dropped = false; } // chevrons
    else if (pType == 6) { a = mod(cell.x + cell.y, 2.0) < 0.5 ? fade : 0.0; col = (pTwo && a == 0.0) ? pC2 : pC1; if (pTwo) a = fade; dropped = false; } // checker
    else if (pType == 7) { float n = fbm(q * 0.6 + pSeed); float t1 = 1.0 - pSize * 0.55; a = smoothstep(t1 - aa * 2.0, t1 + aa * 2.0, n) * fade;
      col = pC1; if (pTwo) { float n2 = fbm(q * 0.6 + pSeed + 31.0); if (n2 > t1 + 0.04) col = pC2; } dropped = false; }   // camo
    else if (pType == 8) {                                                                      // shards
      vec2 g = f * rot(h * 6.283); float d = sdTri(g * vec2(1.0, 0.45 + h), s * 0.6); a = 1.0 - smoothstep(-aa, aa, d); }
    else if (pType == 9) {                                                                      // carbon / kevlar twill
      vec2 c = q * 6.0; vec2 ci = floor(c); bool warp = mod(ci.x + ci.y, 4.0) < 2.0;
      float strand = 0.5 + 0.5 * cos(fract(warp ? c.x : c.y) * 6.2831);
      float gap = smoothstep(0.0, 0.08, min(fract(warp ? c.y : c.x), 1.0 - fract(warp ? c.y : c.x)));
      col = mix(pC1, pC2, ((warp ? 0.55 : 0.2) + strand * 0.25) * (0.6 + 0.4 * gap)); a = fade; dropped = false; }
    else if (pType == 10) {                                                                     // forged carbon
      vec2 c = q * 3.0; vec2 ci = floor(c), cf = fract(c); float b1 = 9.0, b2 = 9.0; vec2 bid = vec2(0.0);
      for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
        vec2 g = vec2(float(x), float(y)); float d = length(g + hash2(ci + g) - cf);
        if (d < b1) { b2 = b1; b1 = d; bid = ci + g; } else if (d < b2) b2 = d; }
      float v = hash(bid * 1.37), an = hash(bid + 5.3) * 6.283;
      float streak = 0.5 + 0.5 * sin(dot(c, vec2(cos(an), sin(an))) * 38.0 + v * 10.0);
      float edge = smoothstep(0.0, 0.07, b2 - b1);
      col = mix(pC1, pC2, (0.12 + 0.7 * v * v) * (0.7 + 0.3 * streak) * (0.55 + 0.45 * edge)); a = fade; dropped = false; }
    else if (pType == 11) {                                                                     // brushed metal
      float n = noise(vec2(q.x * 2.0, q.y * 260.0)) * 0.55 + noise(vec2(q.x * 0.4, q.y * 60.0)) * 0.3 + noise(q * 1.5) * 0.15;
      col = mix(pC1, pC2, n); a = fade; dropped = false; }
    else if (pType == 12) {                                                                     // honeycomb mesh
      const vec2 k = vec2(1.0, 1.7320508); vec2 p = q * 1.5;
      vec4 hc = floor(vec4(p, p - vec2(0.5, 1.0)) / k.xyxy) + 0.5;
      vec4 hh = vec4(p - hc.xy * k, p - (hc.zw + 0.5) * k);
      vec2 hp = dot(hh.xy, hh.xy) < dot(hh.zw, hh.zw) ? hh.xy : hh.zw; hp = abs(hp);
      float e = 0.5 - max(dot(hp, k * 0.5), hp.x);
      a = (1.0 - smoothstep(-aa * 1.5, aa * 1.5, e - pSize * 0.18)) * fade; col = pC1;
      if (pTwo && a < 0.5) { a = fade; col = pC2; } dropped = false; }
    else if (pType == 13) {                                                                     // grid
      vec2 g = abs(fract(q) - 0.5); float d = 0.5 - max(g.x, g.y);
      a = (1.0 - smoothstep(-aa, aa, d - pSize * 0.12)) * fade; col = pC1;
      if (pTwo && a < 0.5) { a = fade; col = pC2; } dropped = false; }
    else if (pType == 14) {                                                                     // waves
      float d = abs(fract(q.x + sin(q.y * 1.7 + pSeed) * 0.35 * (0.3 + pSpread)) - 0.5) - pSize * 0.5 * fade;
      a = 1.0 - smoothstep(-aa, aa, d); col = pC1; dropped = false; }
    else if (pType == 15) {                                                                     // digital camo
      vec2 px = floor(q * 5.0) / 5.0; float n = fbm(px * 0.6 + pSeed); float t1 = 1.0 - pSize * 0.55;
      a = n > t1 ? fade : 0.0; col = pC1;
      if (pTwo) { float n2 = fbm(px * 0.6 + pSeed + 31.0); if (n2 > t1 + 0.04) { col = pC2; a = fade; } } dropped = false; }
    if (dropped) a = 0.0;
    if (pType >= 4 && pType != 8) a *= fg;                           // continuous patterns thin out as opacity
    a *= pAlpha * fo;
    if (a <= 0.002) discard;
    gl_FragColor = vec4(col * a, a);
  }`;

const QUAD_VERT = /* glsl */`varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const LAYER_FRAG = /* glsl */`
  uniform sampler2D layerTex; uniform sampler2D ovTex; uniform float layerOpacity; uniform float ovOpacity; uniform int ovMode;
  uniform bool finishMode; uniform vec3 finishColor;
  varying vec2 vUv;
  void main() {
    vec4 L = texture2D(layerTex, vUv);
    if (ovMode >= 0) {
      vec4 O = texture2D(ovTex, vUv) * ovOpacity; float o = O.a;
      if (ovMode == 0) L = O + L * (1.0 - o);
      else if (ovMode == 1) L = L * (1.0 - o);
      else L = vec4(O.rgb * L.a + L.rgb * (1.0 - o), L.a);
    }
    L *= layerOpacity;
    gl_FragColor = finishMode ? vec4(finishColor * L.a, L.a) : L;
  }`;

const COMMIT_FRAG = /* glsl */`
  uniform sampler2D ovTex; uniform float ovOpacity; uniform bool erase; varying vec2 vUv;
  void main() { vec4 O = texture2D(ovTex, vUv) * ovOpacity; gl_FragColor = erase ? vec4(0.0, 0.0, 0.0, O.a) : O; }`;

const COPY_FRAG = /* glsl */`uniform sampler2D src; varying vec2 vUv; void main() { gl_FragColor = texture2D(src, vUv); }`;
const NOOP_FRAG = /* glsl */`uniform float never; void main() { if (never < 1.0) discard; gl_FragColor = vec4(0.0); }`;

const IMPORT_FRAG = /* glsl */`uniform sampler2D src; varying vec2 vUv;
  void main() { vec4 c = texture2D(src, vUv); gl_FragColor = vec4(c.rgb * c.a, c.a); }`;

const UNPREMUL_FRAG = /* glsl */`uniform sampler2D src; varying vec2 vUv;
  void main() { vec4 c = texture2D(src, vUv); gl_FragColor = c.a > 0.0 ? vec4(c.rgb / c.a, c.a) : vec4(0.0); }`;

const SEED_FRAG = /* glsl */`uniform sampler2D src; uniform sampler2D mask; varying vec2 vUv;
  void main() { gl_FragColor = vec4(texture2D(src, vUv).rgb, texture2D(mask, vUv).a > 0.5 ? 1.0 : 0.0); }`;

const DILATE_FRAG = /* glsl */`uniform sampler2D src; uniform vec2 texel; varying vec2 vUv;
  void main() {
    vec4 c = texture2D(src, vUv);
    if (c.a > 0.5) { gl_FragColor = c; return; }
    vec3 acc = vec3(0.0); float n = 0.0;
    for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
      vec4 s = texture2D(src, vUv + vec2(float(x), float(y)) * texel);
      if (s.a > 0.5) { acc += s.rgb; n += 1.0; }
    }
    gl_FragColor = n > 0.0 ? vec4(acc / n, 1.0) : c;
  }`;

// each output pixel = the highest alpha in its k x k block of the source (used to ask "is this layer empty?")
const MAXA_FRAG = /* glsl */`uniform sampler2D src; uniform vec2 srcSize; uniform float k;
  void main() {
    vec2 base = floor(gl_FragCoord.xy) * k; float m = 0.0;
    for (int y = 0; y < 16; y++) { if (float(y) >= k) break;
      for (int x = 0; x < 16; x++) { if (float(x) >= k) break;
        vec2 p = base + vec2(float(x), float(y)) + 0.5;
        if (p.x < srcSize.x && p.y < srcSize.y) m = max(m, texture2D(src, p / srcSize).a); } }
    gl_FragColor = vec4(m);
  }`;

function rt(w, h, mip = false) {
  const t = new THREE.WebGLRenderTarget(w, h, {
    type: THREE.UnsignedByteType, format: THREE.RGBAFormat, depthBuffer: false, stencilBuffer: false,
    generateMipmaps: mip, minFilter: mip ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter, magFilter: THREE.LinearFilter,
  });
  t.texture.colorSpace = THREE.NoColorSpace;
  return t;
}

export class PaintEngine {
  constructor(renderer, geometry, width, height, bounds, islandCount = 1) {
    this.r = renderer; this.w = width; this.h = height; this.bounds = bounds;
    const mw = 256, mh = Math.max(1, Math.ceil(islandCount / mw));
    this.maskTex = new THREE.DataTexture(new Uint8Array(mw * mh * 4), mw, mh, THREE.RGBAFormat);
    this.maskTex.magFilter = this.maskTex.minFilter = THREE.NearestFilter; this.maskTex.needsUpdate = true;
    this.cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.composite = rt(width, height, true);
    this.finishRT = rt(Math.max(1, width >> 1), Math.max(1, height >> 1), true);
    for (const t of [this.composite, this.finishRT]) {
      t.texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
      t.texture.wrapS = t.texture.wrapT = THREE.RepeatWrapping;       // some cars' UVs reach past 0..1
    }
    this.overlay = rt(width, height);
    this.ovMode = -1; this.ovOpacity = 1;
    this.layers = []; this.active = null;
    this.background = new THREE.Color(0.8, 0.8, 0.8);
    this.baseFinish = [1, 1];                                   // gloss, reflection of the bare car
    const common = { filterIsland: { value: -1 }, filterPart: { value: -1 }, useMask: { value: false }, islandMask: { value: null },
                     maskSize: { value: new THREE.Vector2(mw, mh) }, cullMode: { value: 0 }, cullSphere: { value: new THREE.Vector4() },
                     dabs: { value: Array.from({ length: MAXD }, () => new THREE.Vector4()) }, dabCount: { value: 0 } };
    const mk = (frag, uniforms, blend) => new THREE.ShaderMaterial({
      vertexShader: UV_VERT, fragmentShader: frag, uniforms: { ...THREE.UniformsUtils.clone(common), ...uniforms },
      side: THREE.DoubleSide, depthTest: false, depthWrite: false, transparent: true, ...blend });
    const over = { blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor };
    const max = { blending: THREE.CustomBlending, blendEquation: THREE.MaxEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor };
    this.mats = {
      dab: mk(DAB_FRAG, { dabN: { value: Array.from({ length: MAXD }, () => new THREE.Vector4()) }, hardness: { value: 0.5 }, color: { value: new THREE.Color() }, protect: { value: false } }, max),
      decal: mk(DECAL_FRAG, { decalTex: { value: null }, dC: { value: new THREE.Vector3() }, dR: { value: new THREE.Vector3() }, dU: { value: new THREE.Vector3() },
        dN: { value: new THREE.Vector3() }, dSize: { value: new THREE.Vector2(1, 1) }, depth: { value: 0.2 }, opacity: { value: 1 }, tint: { value: false }, color: { value: new THREE.Color() } }, over),
      fill: mk(FILL_FRAG, { color: { value: new THREE.Vector4(1, 1, 1, 1) } }, over),
      grad: mk(GRAD_FRAG, { gA: { value: new THREE.Vector3() }, gB: { value: new THREE.Vector3() }, gType: { value: 0 }, gN: { value: 2 }, gBlend: { value: 0 },
        gRepeat: { value: 1 }, gCol: { value: Array.from({ length: MAX_STOPS }, () => new THREE.Vector4()) }, gPos: { value: new Array(MAX_STOPS).fill(1) } }, over),
      pattern: mk(PATTERN_FRAG, { pType: { value: 0 }, pProj: { value: 0 }, pAngle: { value: 0 }, pSpacing: { value: 0.1 }, pSize: { value: 0.6 }, pSpread: { value: 0 },
        pDrop: { value: 0 }, pSeed: { value: 1 }, pC1: { value: new THREE.Color() }, pC2: { value: new THREE.Color() }, pTwo: { value: false }, pAlpha: { value: 1 },
        pFadeType: { value: 0 }, fA: { value: new THREE.Vector3() }, fB: { value: new THREE.Vector3(0, 0, 1) }, pFadeStart: { value: 0 }, pFadeEnd: { value: 1 },
        pFadeCurve: { value: 1 }, pFadeFx: { value: 1 } }, over),
      mask: mk(FILL_FRAG, { color: { value: new THREE.Vector4(1, 1, 1, 1) } }, { blending: THREE.NoBlending }),
    };
    this.mats.pattern.extensions = { derivatives: true };
    for (const m of Object.values(this.mats)) m.uniforms.islandMask.value = this.maskTex;     // shared, not cloned
    this.uvMesh = new THREE.Mesh(geometry, this.mats.dab); this.uvMesh.frustumCulled = false;
    this.uvScene = new THREE.Scene(); this.uvScene.add(this.uvMesh);
    const q = (frag, uniforms, blend = {}) => new THREE.ShaderMaterial({ vertexShader: QUAD_VERT, fragmentShader: frag, uniforms,
      depthTest: false, depthWrite: false, transparent: true, ...blend });
    this.q = {
      layer: q(LAYER_FRAG, { layerTex: { value: null }, ovTex: { value: null }, layerOpacity: { value: 1 }, ovOpacity: { value: 1 }, ovMode: { value: -1 },
                             finishMode: { value: false }, finishColor: { value: new THREE.Color() } },
        { blending: THREE.CustomBlending, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor, blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor }),
      commit: q(COMMIT_FRAG, { ovTex: { value: null }, ovOpacity: { value: 1 }, erase: { value: false } }),
      copy: q(COPY_FRAG, { src: { value: null } }, { blending: THREE.NoBlending }),
      noop: q(NOOP_FRAG, { never: { value: 0 } }),
      import: q(IMPORT_FRAG, { src: { value: null } }, { blending: THREE.NoBlending }),
      unpremul: q(UNPREMUL_FRAG, { src: { value: null } }, { blending: THREE.NoBlending }),
      seed: q(SEED_FRAG, { src: { value: null }, mask: { value: null } }, { blending: THREE.NoBlending }),
      dilate: q(DILATE_FRAG, { src: { value: null }, texel: { value: new THREE.Vector2() } }, { blending: THREE.NoBlending }),
      maxA: q(MAXA_FRAG, { src: { value: null }, srcSize: { value: new THREE.Vector2() }, k: { value: 16 } }, { blending: THREE.NoBlending }),
    };
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.q.copy); this.quad.frustumCulled = false;
    this.quadScene = new THREE.Scene(); this.quadScene.add(this.quad);
    this.clearOverlay();
  }

  // ---- low level ---------------------------------------------------------------------------
  _draw(mat, target, clear = null) {
    const r = this.r, prev = r.getRenderTarget(), ac = r.autoClear;
    r.setRenderTarget(target);
    if (clear) { r.setClearColor(clear[0], clear[1]); r.clear(true, false, false); }
    r.autoClear = false;
    if (mat.vertexShader === QUAD_VERT) { this.quad.material = mat; r.render(this.quadScene, this.cam); }
    else { this.uvMesh.material = mat; r.render(this.uvScene, this.cam); }
    r.autoClear = ac; r.setRenderTarget(prev);
  }
  _filter(mat, f = {}) {
    mat.uniforms.filterIsland.value = f?.island ?? -1;
    mat.uniforms.filterPart.value = f?.part ?? -1;
    mat.uniforms.useMask.value = !!f?.islands;
    if (f?.islands) this._setMask(f.islands);
    mat.uniforms.cullMode.value = 0;
  }
  _setMask(ids) {
    const d = this.maskTex.image.data; d.fill(0);
    for (const i of ids) if (i >= 0 && i * 4 < d.length) d[i * 4] = 255;
    this.maskTex.needsUpdate = true;
  }
  newTarget() { return rt(this.w, this.h); }
  copy(src, dst) { this.q.copy.uniforms.src.value = src.texture; this._draw(this.q.copy, dst); }
  layerBytes() { return this.w * this.h * 4; }

  // ---- overlay operations (what the active tool is doing right now) ------------------------
  clearOverlay() { this._draw(this.q.noop, this.overlay, [0x000000, 0]); this.ovMode = -1; }
  setOverlayMode(mode, opacity = 1) { this.ovMode = mode; this.ovOpacity = opacity; }   // 0 paint, 1 erase, 2 clip (lock alpha)

  /** list: [{p: Vector3, n: Vector3, r: radius, island}] in car space. */
  dabs(list, { hardness = 0.5, color = '#ffffff', protect = false, filter } = {}) {
    const m = this.mats.dab;
    this._filter(m, filter);
    m.uniforms.hardness.value = Math.min(0.99, Math.max(0, hardness));
    rawColor(color, m.uniforms.color.value); m.uniforms.protect.value = !!protect;
    for (let i = 0; i < list.length; i += MAXD) {
      const chunk = list.slice(i, i + MAXD);
      chunk.forEach((d, k) => { m.uniforms.dabs.value[k].set(d.p.x, d.p.y, d.p.z, d.r); m.uniforms.dabN.value[k].set(d.n.x, d.n.y, d.n.z, d.island ?? -1); });
      m.uniforms.dabCount.value = chunk.length; m.uniforms.cullMode.value = 1;
      this._draw(m, this.overlay);
    }
  }

  /** frame: {c, r, u, n (Vector3, car space), w, h (metres)}. tint: colour to replace the image's RGB. */
  decal(tex, frame, { opacity = 1, depth, filter, tint = null, target = this.overlay } = {}) {
    const m = this.mats.decal, u = m.uniforms;
    this._filter(m, filter);
    u.decalTex.value = tex; u.dC.value.copy(frame.c); u.dR.value.copy(frame.r); u.dU.value.copy(frame.u); u.dN.value.copy(frame.n);
    u.dSize.value.set(frame.w, frame.h); u.depth.value = depth ?? Math.max(0.1, Math.min(0.5, Math.min(frame.w, frame.h) * 0.6));
    u.opacity.value = opacity; u.tint.value = tint != null; if (tint != null) rawColor(tint, u.color.value);
    u.cullMode.value = 2; u.cullSphere.value.set(frame.c.x, frame.c.y, frame.c.z, 0.5 * Math.hypot(frame.w, frame.h) + 0.05);
    this._draw(m, target);
  }

  fill(color, alpha = 1, filter) {
    const m = this.mats.fill; this._filter(m, filter);
    const c = rawColor(color); m.uniforms.color.value.set(c.r, c.g, c.b, alpha);
    this._draw(m, this.overlay);
  }

  /** stops: [{pos 0..1, color, alpha}], any order. blend: linear | smooth | hard. repeat: how many times it repeats. */
  gradient({ a, b, type, stops, blend = 'linear', repeat = 1, filter }) {
    const m = this.mats.grad, u = m.uniforms; this._filter(m, filter);
    u.gA.value.copy(a); u.gB.value.copy(b); u.gType.value = { radial: 1, reflected: 2 }[type] ?? 0;
    const list = [...stops].sort((p, q) => p.pos - q.pos).slice(0, MAX_STOPS);
    if (list.length === 1) list.push({ ...list[0], pos: 1 });
    list.forEach((s, i) => { const c = rawColor(s.color); u.gCol.value[i].set(c.r, c.g, c.b, s.alpha ?? 1); u.gPos.value[i] = s.pos; });
    u.gN.value = list.length; u.gBlend.value = { smooth: 1, hard: 2 }[blend] ?? 0; u.gRepeat.value = Math.max(1, repeat);
    this._draw(m, this.overlay);
  }

  pattern(p, filter) {
    const m = this.mats.pattern, u = m.uniforms; this._filter(m, filter);
    u.pType.value = p.type; u.pProj.value = p.proj ?? 0; u.pAngle.value = (p.angle ?? 0) * Math.PI / 180;
    u.pSpacing.value = p.spacing; u.pSize.value = p.size ?? 0.6; u.pSpread.value = p.spread ?? 0; u.pDrop.value = p.drop ?? 0; u.pSeed.value = p.seed ?? 1;
    rawColor(p.c1, u.pC1.value); rawColor(p.c2 ?? p.c1, u.pC2.value); u.pTwo.value = !!p.two; u.pAlpha.value = p.alpha ?? 1;
    u.pFadeType.value = { linear: 1, radial: 2 }[p.fadeType] ?? 0;
    if (p.fadeA) u.fA.value.fromArray(p.fadeA); if (p.fadeB) u.fB.value.fromArray(p.fadeB);
    u.pFadeStart.value = p.fadeStart ?? 0; u.pFadeEnd.value = p.fadeEnd ?? 1; u.pFadeCurve.value = p.fadeCurve ?? 1; u.pFadeFx.value = p.fadeFx ?? 1;
    this._draw(m, this.overlay);
  }

  // ---- layers ---------------------------------------------------------------------------------
  _layer(props) {
    return { id: crypto.randomUUID?.() ?? String(Math.random()).slice(2), visible: true, opacity: 1, lock: false,
             finishOnly: false, finish: null, ...props };                  // finish null = same as the car base
  }
  addLayer(name, index = this.layers.length) {
    const layer = this._layer({ name, kind: 'paint', rt: this.newTarget() });
    this._draw(this.q.noop, layer.rt, [0x000000, 0]);
    this.layers.splice(index, 0, layer);
    return layer;
  }
  addDecalLayer(name, index = this.layers.length) {
    const layer = this._layer({ name, kind: 'decal', decal: { tex: null, frames: [], filter: null } });
    this.layers.splice(index, 0, layer);
    return layer;
  }
  duplicate(layer) {
    const copy = this._layer({ ...layer, id: undefined, name: layer.name + ' copy', finish: layer.finish ? [...layer.finish] : null });
    copy.id = crypto.randomUUID?.() ?? String(Math.random()).slice(2);
    if (layer.kind === 'paint') { copy.rt = this.newTarget(); this.copy(layer.rt, copy.rt); }
    return copy;
  }
  importImage(layer, image) {
    const tex = new THREE.Texture(image); tex.flipY = false; tex.colorSpace = THREE.NoColorSpace; tex.needsUpdate = true;
    tex.minFilter = THREE.LinearFilter; tex.generateMipmaps = false;
    this.q.import.uniforms.src.value = tex; this._draw(this.q.import, layer.rt);
    tex.dispose();
  }
  /** Bake the overlay into a paint layer. Returns the layer's previous render target (for undo). */
  commit(layer) {
    if (this.ovMode < 0) return null;
    const before = this.newTarget(); this.copy(layer.rt, before);
    const m = this.q.commit;
    m.uniforms.ovTex.value = this.overlay.texture; m.uniforms.ovOpacity.value = this.ovOpacity;
    const mode = this.ovMode === 0 && layer.lock ? 2 : this.ovMode;
    m.uniforms.erase.value = mode === 1;
    m.blending = THREE.CustomBlending; m.blendEquation = THREE.AddEquation;
    if (mode === 1) { m.blendSrc = THREE.ZeroFactor; m.blendDst = THREE.OneMinusSrcAlphaFactor; m.blendSrcAlpha = null; m.blendDstAlpha = null; }
    else if (mode === 2) { m.blendSrc = THREE.DstAlphaFactor; m.blendDst = THREE.OneMinusSrcAlphaFactor; m.blendSrcAlpha = THREE.ZeroFactor; m.blendDstAlpha = THREE.OneFactor; }
    else { m.blendSrc = THREE.OneFactor; m.blendDst = THREE.OneMinusSrcAlphaFactor; m.blendSrcAlpha = null; m.blendDstAlpha = null; }
    m.needsUpdate = true;
    this._draw(m, layer.rt);
    this.clearOverlay();
    return before;
  }
  _drawDecal(L, target, finish, opacity = L.opacity) {
    const d = L.decal; if (!d?.tex) return;
    const fin = L.finish || this.baseFinish;
    for (const f of d.frames) this.decal(d.tex, f, { opacity, filter: f.filter, depth: f.depth, tint: finish ? [fin[0], fin[1], 0] : d.tint, target });
  }
  _drawPaint(L, target, finish) {
    const m = this.q.layer, u = m.uniforms;
    u.layerTex.value = L.rt.texture; u.layerOpacity.value = L.opacity;
    const active = L === this.active && this.ovMode >= 0;
    u.ovMode.value = active ? (this.ovMode === 0 && L.lock ? 2 : this.ovMode) : -1;
    u.ovTex.value = this.overlay.texture; u.ovOpacity.value = this.ovOpacity;
    const fin = L.finish || this.baseFinish;
    u.finishMode.value = finish; u.finishColor.value.setRGB(fin[0], fin[1], 0, THREE.LinearSRGBColorSpace);
    this._draw(m, target);
  }
  /** Draw `upper` onto the paint layer `lower`. Returns lower's previous target (for undo). */
  mergeDown(upper, lower) {
    const before = this.newTarget(); this.copy(lower.rt, before);
    if (upper.kind === 'decal') { this._drawDecal(upper, lower.rt, false); return before; }
    const m = this.q.layer;
    m.uniforms.layerTex.value = upper.rt.texture; m.uniforms.layerOpacity.value = upper.opacity; m.uniforms.ovMode.value = -1; m.uniforms.finishMode.value = false;
    const keep = [m.blendSrcAlpha, m.blendDstAlpha];
    m.blendSrcAlpha = THREE.OneFactor; m.blendDstAlpha = THREE.OneMinusSrcAlphaFactor; m.needsUpdate = true;
    this._draw(m, lower.rt);
    [m.blendSrcAlpha, m.blendDstAlpha] = keep; m.needsUpdate = true;
    return before;
  }
  /** Turn a decal layer into pixels (a new render target holding just that decal). */
  rasterize(layer) {
    const t = this.newTarget(); this._draw(this.q.noop, t, [0x000000, 0]);
    this._drawDecal(layer, t, false, 1);
    return t;
  }

  // ---- output ------------------------------------------------------------------------------------
  _accumulate(target, finish) {
    const tex = target.texture, mip = tex.generateMipmaps;
    tex.generateMipmaps = false;
    const bg = finish ? new THREE.Color().setRGB(this.baseFinish[0], this.baseFinish[1], 0, THREE.LinearSRGBColorSpace) : this.background;
    this._draw(this.q.noop, target, [bg, 1]);
    for (const L of this.layers) {
      if (!L.visible || (L.finishOnly && !finish)) continue;
      if (L.kind === 'decal') this._drawDecal(L, target, finish);
      else this._drawPaint(L, target, finish);
    }
    tex.generateMipmaps = mip;
    if (mip) this._draw(this.q.noop, target);                // one mipmap rebuild at the end
  }
  render() { this._accumulate(this.composite, false); }
  renderFinish() { this._accumulate(this.finishRT, true); }

  /** Pixels of a target as RGBA, rows top-down (image order). */
  readPixels(target, unpremultiply = false) {
    let src = target;
    if (unpremultiply) { src = this.newTarget(); this.q.unpremul.uniforms.src.value = target.texture; this._draw(this.q.unpremul, src); }
    const buf = new Uint8Array(src.width * src.height * 4);
    this.r.readRenderTargetPixels(src, 0, 0, src.width, src.height, buf);
    if (src !== target) src.dispose();
    return buf;   // row 0 = v 0 = top of the livery image
  }
  /** True when a paint layer has anything on it (reduced on the GPU, so it's quick even at 4K). */
  hasPaint(layer) {
    if (!layer?.rt) return false;
    let src = layer.rt, sw = src.width, sh = src.height;
    const tmp = [], u = this.q.maxA.uniforms;
    while (sw > 32 || sh > 32) {
      const w = Math.ceil(sw / 16), h = Math.ceil(sh / 16), t = rt(w, h);
      u.src.value = src.texture; u.srcSize.value.set(sw, sh); u.k.value = 16;
      this._draw(this.q.maxA, t, [0x000000, 0]);
      tmp.push(t); src = t; sw = w; sh = h;
    }
    const buf = new Uint8Array(sw * sh * 4);
    this.r.readRenderTargetPixels(src, 0, 0, sw, sh, buf);
    tmp.forEach(t => t.dispose());
    for (let i = 3; i < buf.length; i += 4) if (buf[i] > 0) return true;
    return false;
  }
  _dilated(src) {
    const mask = this.newTarget(); this._filter(this.mats.mask); this._draw(this.mats.mask, mask, [0x000000, 0]);
    let a = this.newTarget(), b = this.newTarget();
    this.q.seed.uniforms.src.value = src.texture; this.q.seed.uniforms.mask.value = mask.texture; this._draw(this.q.seed, a);
    this.q.dilate.uniforms.texel.value.set(1 / this.w, 1 / this.h);
    for (let i = 0; i < 12; i++) { this.q.dilate.uniforms.src.value = a.texture; this._draw(this.q.dilate, b); [a, b] = [b, a]; }
    const buf = new Uint8Array(this.w * this.h * 4);
    this.r.readRenderTargetPixels(a, 0, 0, this.w, this.h, buf);
    for (let i = 3; i < buf.length; i += 4) buf[i] = 255;
    [mask, a, b].forEach(t => t.dispose());
    return buf;
  }
  /** Grow the composite's colours a few pixels past every panel edge, so the 3D view shows no seams. */
  dilateComposite(passes = 8) {
    if (!this._dil) {
      this._dil = { mask: this.newTarget(), a: this.newTarget(), b: this.newTarget() };
      this._filter(this.mats.mask); this._draw(this.mats.mask, this._dil.mask, [0x000000, 0]);
    }
    let { a, b } = this._dil;
    this.q.seed.uniforms.src.value = this.composite.texture; this.q.seed.uniforms.mask.value = this._dil.mask.texture;
    this._draw(this.q.seed, a);
    this.q.dilate.uniforms.texel.value.set(1 / this.w, 1 / this.h);
    for (let i = 0; i < passes; i++) { this.q.dilate.uniforms.src.value = a.texture; this._draw(this.q.dilate, b); [a, b] = [b, a]; }
    this.copy(a, this.composite);
  }
  /** The final livery: composite, with colours grown 12px past every panel edge (no seams in game). */
  exportPixels() {
    const full = rt(this.w, this.h);
    this._accumulate(full, false);
    const buf = this._dilated(full); full.dispose();
    return buf;
  }
  /** Finish map at full resolution: R = gloss, G = reflection. */
  exportFinish() {
    const full = rt(this.w, this.h);
    this._accumulate(full, true);
    const buf = this._dilated(full); full.dispose();
    return buf;
  }
  sample(uv) {                                    // colour of the composite at a livery UV
    const buf = new Uint8Array(4), w = this.w, h = this.h;
    const x = ((Math.floor(uv.x * w) % w) + w) % w, y = ((Math.floor(uv.y * h) % h) + h) % h;
    this.r.readRenderTargetPixels(this.composite, x, y, 1, 1, buf);
    return buf;
  }
  disposeTarget(t) { t?.dispose(); }
  dispose() {
    [this.composite, this.finishRT, this.overlay, ...this.layers.filter(l => l.rt).map(l => l.rt), ...Object.values(this._dil || {})].forEach(t => t.dispose());
    Object.values(this.mats).forEach(m => m.dispose()); Object.values(this.q).forEach(m => m.dispose());
    this.maskTex.dispose();
  }
}
