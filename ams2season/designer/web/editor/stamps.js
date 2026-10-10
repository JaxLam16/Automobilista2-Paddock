// Everything that becomes a decal image: text (with fonts, outline, number boards), shapes (built-in and
// custom polygons) and uploaded images (with automatic background removal).

// ---- fonts ---------------------------------------------------------------------------------------
export const GOOGLE_FONTS = [
  'Anton', 'Bebas Neue', 'Oswald', 'Teko', 'Russo One', 'Orbitron', 'Audiowide', 'Racing Sans One', 'Black Ops One',
  'Bungee', 'Bungee Inline', 'Exo 2', 'Rajdhani', 'Saira Condensed', 'Saira Stencil One', 'Titillium Web', 'Barlow Condensed',
  'Archivo Black', 'Montserrat', 'Roboto Condensed', 'Kanit', 'Michroma', 'Squada One', 'Faster One', 'Monoton',
  'Staatliches', 'Alfa Slab One', 'Chakra Petch', 'Goldman', 'Iceland', 'Jura', 'Quantico', 'Play', 'Share Tech Mono',
  'Sarpanch', 'Zen Dots', 'Righteous', 'Days One', 'Electrolize', 'Graduate', 'Krona One', 'Passion One', 'Rubik Mono One',
  'Syncopate', 'Ultra', 'Wallpoet', 'Bangers', 'Press Start 2P', 'Permanent Marker', 'Rock Salt', 'Kaushan Script',
  'Yellowtail', 'Pacifico', 'Lobster', 'Dancing Script', 'Big Shoulders Display', 'Black Han Sans', 'Changa One',
];
export const SYSTEM_FONTS = [
  'Arial', 'Arial Black', 'Bahnschrift', 'Impact', 'Segoe UI', 'Segoe UI Black', 'Franklin Gothic Medium', 'Verdana', 'Tahoma',
  'Trebuchet MS', 'Calibri', 'Candara', 'Corbel', 'Consolas', 'Georgia', 'Times New Roman', 'Palatino Linotype',
  'Courier New', 'Lucida Console', 'Comic Sans MS', 'Gabriola', 'Helvetica', 'Futura', 'Avenir Next Condensed',
];

export function loadGoogleFonts() {
  for (const f of GOOGLE_FONTS) {                       // one stylesheet per family, so one bad name can't break the rest
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(f).replace(/%20/g, '+')}&display=swap`;
    document.head.append(l);
  }
}

const probe = document.createElement('canvas').getContext('2d');
export function systemFontAvailable(name) {
  const t = 'mmmmmmmmmmlliWW@#0123';
  return ['monospace', 'serif', 'sans-serif'].some(base => {
    probe.font = `72px ${base}`; const w0 = probe.measureText(t).width;
    probe.font = `72px "${name}", ${base}`; return Math.abs(probe.measureText(t).width - w0) > 0.5;
  });
}

const fontSpec = (o, px) => `${o.italic ? 'italic ' : ''}${o.bold ? '700' : '400'} ${px}px "${o.font}", "Arial Black", sans-serif`;

export async function ensureFont(o) {
  try { await Promise.race([document.fonts.load(fontSpec(o, 64), o.text || 'A'), new Promise(r => setTimeout(r, 2500))]); } catch {}
}

// ---- text ------------------------------------------------------------------------------------------
export const TEXT_DEFAULTS = {
  text: '23', font: 'Anton', bold: false, italic: false, color: '#ffffff', outline: 0, outlineColor: '#000000',
  spacing: 0, lineHeight: 1.0, align: 'center', skew: 0, stretch: 1, board: 'none', boardColor: '#ffffff', boardPad: 0.25,
  boardOutline: 0, boardOutlineColor: '#000000',
};

/** Render text to a canvas. Returns {canvas, aspect}. Sizes are relative to the font size. */
export function renderText(opts) {
  const o = { ...TEXT_DEFAULTS, ...opts };
  const S = 220;
  const lines = String(o.text || ' ').split('\n');
  const ctx = document.createElement('canvas').getContext('2d');
  ctx.font = fontSpec(o, S);
  const hasLS = 'letterSpacing' in ctx;
  const sp = o.spacing * S;
  const lineW = s => {
    if (hasLS) { ctx.letterSpacing = `${sp}px`; const w = ctx.measureText(s).width - (s.length ? sp : 0); ctx.letterSpacing = '0px'; return w; }
    return [...s].reduce((w, ch) => w + ctx.measureText(ch).width, 0) + sp * Math.max(0, [...s].length - 1);
  };
  let asc = 0, desc = 0;
  for (const l of lines) {
    const m = ctx.measureText(l || 'A');
    asc = Math.max(asc, m.actualBoundingBoxAscent || S * 0.75); desc = Math.max(desc, m.actualBoundingBoxDescent || 0);
  }
  if (lines.length > 1) { const m = ctx.measureText('ÁgjpqyX'); asc = Math.max(asc, m.actualBoundingBoxAscent); desc = Math.max(desc, m.actualBoundingBoxDescent); }
  const lh = (asc + desc) * (lines.length > 1 ? o.lineHeight * 1.15 : 1);
  const widths = lines.map(lineW);
  const k = Math.tan((o.skew || 0) * Math.PI / 180);
  const blockH = lh * (lines.length - 1) + asc + desc;
  const blockW = Math.max(1, ...widths) * o.stretch + Math.abs(k) * blockH;
  const ow = o.outline * S;
  const bpad = o.board !== 'none' ? o.boardPad * S : 0;
  const bo = o.board !== 'none' ? o.boardOutline * S : 0;
  let bw = blockW + 2 * ow + 2 * bpad, bh = blockH + 2 * ow + 2 * bpad;
  if (o.board === 'circle') bw = bh = Math.max(bw, bh) * 1.08;
  const margin = 4 + bo;
  let W = bw + 2 * margin, H = bh + 2 * margin;
  const scale = Math.min(1, 2048 / Math.max(W, H));
  const c = document.createElement('canvas');
  c.width = Math.max(4, Math.ceil(W * scale)); c.height = Math.max(4, Math.ceil(H * scale));
  const g = c.getContext('2d');
  g.scale(scale, scale);
  if (o.board !== 'none') {
    g.save();
    const x = margin, y = margin;
    g.beginPath();
    if (o.board === 'circle') g.ellipse(x + bw / 2, y + bh / 2, bw / 2, bh / 2, 0, 0, Math.PI * 2);
    else if (o.board === 'oval') g.ellipse(x + bw / 2, y + bh / 2, bw / 2, bh / 2, 0, 0, Math.PI * 2);
    else roundRect(g, x, y, bw, bh, o.board === 'rounded' ? Math.min(bw, bh) * 0.18 : o.board === 'pill' ? Math.min(bw, bh) / 2 : 0);
    g.fillStyle = o.boardColor; g.fill();
    if (bo > 0) { g.lineWidth = bo * 2; g.strokeStyle = o.boardOutlineColor; g.save(); g.clip(); g.stroke(); g.restore(); }
    g.restore();
  }
  const cx = margin + bw / 2, top = margin + (bh - blockH) / 2;
  g.font = fontSpec(o, S); g.textBaseline = 'alphabetic'; g.lineJoin = 'round'; g.miterLimit = 2;
  const yc = top + blockH / 2, kk = Math.abs(k) * blockH / 2;
  const drawLine = (l, i, stroke) => {
    const w = widths[i] * o.stretch, y = top + asc + i * lh;
    const startX = o.align === 'left' ? cx - blockW / 2 + kk : o.align === 'right' ? cx + blockW / 2 - kk - w : cx - w / 2;
    g.save();
    // (x, y) -> (scale * (startX + stretch * x - k * (y - yc)), scale * y): stretch and slant around the block centre
    g.setTransform(scale * o.stretch, 0, -k * scale, scale, scale * (startX + k * yc), 0);
    if (hasLS) g.letterSpacing = `${sp}px`;
    const put = (s, x) => stroke ? g.strokeText(s, x, y) : g.fillText(s, x, y);
    if (hasLS || !sp) put(l, 0);
    else { let x = 0; for (const ch of l) { put(ch, x); x += g.measureText(ch).width + sp; } }
    g.restore();
  };
  if (ow > 0) { g.lineWidth = ow * 2; g.strokeStyle = o.outlineColor; lines.forEach((l, i) => drawLine(l, i, true)); }
  g.fillStyle = o.color; lines.forEach((l, i) => drawLine(l, i, false));
  return { canvas: c, aspect: c.width / c.height };
}

function roundRect(g, x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  g.moveTo(x + r, y); g.lineTo(x + w - r, y); g.arcTo(x + w, y, x + w, y + r, r); g.lineTo(x + w, y + h - r);
  g.arcTo(x + w, y + h, x + w - r, y + h, r); g.lineTo(x + r, y + h); g.arcTo(x, y + h, x, y + h - r, r);
  g.lineTo(x, y + r); g.arcTo(x, y, x + r, y, r); g.closePath();
}

// ---- shapes ------------------------------------------------------------------------------------------
// Each shape draws a path into the unit box (0..1 x 0..1); params it uses are listed for the UI.
const poly = pts => g => { g.moveTo(pts[0][0], pts[0][1]); for (const p of pts.slice(1)) g.lineTo(p[0], p[1]); g.closePath(); };
export const SHAPES = {
  rect:      { name: 'Rectangle', params: ['radius'], draw: (g, o) => roundRect(g, 0, 0, 1, 1, o.radius * 0.5) },
  circle:    { name: 'Circle', draw: g => g.ellipse(0.5, 0.5, 0.5, 0.5, 0, 0, Math.PI * 2) },
  ring:      { name: 'Ring', params: ['thickness'], evenodd: true, draw: (g, o) => {
    g.ellipse(0.5, 0.5, 0.5, 0.5, 0, 0, Math.PI * 2); const r = 0.5 * (1 - o.thickness);
    g.moveTo(0.5 + r, 0.5); g.ellipse(0.5, 0.5, r, r, 0, 0, Math.PI * 2, true); } },
  triangle:  { name: 'Triangle', draw: poly([[0.5, 0], [1, 1], [0, 1]]) },
  rtriangle: { name: 'Right triangle', draw: poly([[0, 0], [1, 1], [0, 1]]) },
  diamond:   { name: 'Diamond', draw: poly([[0.5, 0], [1, 0.5], [0.5, 1], [0, 0.5]]) },
  polygon:   { name: 'Polygon', params: ['sides'], draw: (g, o) => {
    const n = Math.round(o.sides), off = Math.PI / 2 + (n % 2 ? 0 : Math.PI / n);
    for (let i = 0; i < n; i++) { const a = off + i * 2 * Math.PI / n; g[i ? 'lineTo' : 'moveTo'](0.5 + 0.5 * Math.cos(a), 0.5 + 0.5 * Math.sin(a)); }
    g.closePath(); } },
  star:      { name: 'Star', params: ['points', 'inner'], draw: (g, o) => {
    const n = Math.round(o.points);
    for (let i = 0; i < n * 2; i++) { const a = -Math.PI / 2 + i * Math.PI / n, r = i % 2 ? 0.5 * o.inner : 0.5;
      g[i ? 'lineTo' : 'moveTo'](0.5 + r * Math.cos(a), 0.5 + r * Math.sin(a)); }
    g.closePath(); } },
  chevron:   { name: 'Chevron', params: ['thickness'], draw: (g, o) => { const t = o.thickness;
    poly([[0, 0], [t, 0], [1, 0.5], [t, 1], [0, 1], [1 - t, 0.5]])(g); } },
  arrow:     { name: 'Arrow', params: ['thickness'], draw: (g, o) => { const s = o.thickness / 2, hl = 0.42;
    poly([[0, 0.5 - s], [1 - hl, 0.5 - s], [1 - hl, 0], [1, 0.5], [1 - hl, 1], [1 - hl, 0.5 + s], [0, 0.5 + s]])(g); } },
  darrow:    { name: 'Double arrow', params: ['thickness'], draw: (g, o) => { const s = o.thickness / 2, hl = 0.3;
    poly([[0, 0.5], [hl, 0], [hl, 0.5 - s], [1 - hl, 0.5 - s], [1 - hl, 0], [1, 0.5], [1 - hl, 1], [1 - hl, 0.5 + s], [hl, 0.5 + s], [hl, 1]])(g); } },
  slant:     { name: 'Parallelogram', params: ['slant'], draw: (g, o) => poly([[o.slant, 0], [1, 0], [1 - o.slant, 1], [0, 1]])(g) },
  trapezoid: { name: 'Trapezoid', params: ['slant'], draw: (g, o) => poly([[o.slant / 2, 0], [1 - o.slant / 2, 0], [1, 1], [0, 1]])(g) },
  cross:     { name: 'Plus', params: ['thickness'], draw: (g, o) => { const a = 0.5 - o.thickness / 2, b = 0.5 + o.thickness / 2;
    poly([[a, 0], [b, 0], [b, a], [1, a], [1, b], [b, b], [b, 1], [a, 1], [a, b], [0, b], [0, a], [a, a]])(g); } },
  bolt:      { name: 'Lightning', draw: poly([[0.62, 0], [0.12, 0.58], [0.45, 0.58], [0.32, 1], [0.88, 0.38], [0.54, 0.38], [0.72, 0]]) },
  heart:     { name: 'Heart', draw: g => { g.moveTo(0.5, 1); g.bezierCurveTo(-0.15, 0.55, 0.05, -0.1, 0.5, 0.22);
    g.bezierCurveTo(0.95, -0.1, 1.15, 0.55, 0.5, 1); g.closePath(); } },
  half:      { name: 'Half circle', draw: g => { g.moveTo(0, 1); g.ellipse(0.5, 1, 0.5, 1, 0, Math.PI, 0); g.closePath(); } },
  stripes:   { name: 'Twin stripes', params: ['thickness'], draw: (g, o) => { const gap = o.thickness * 0.6, w = (1 - gap) / 2;
    g.rect(0, 0, w, 1); g.rect(1 - w, 0, w, 1); } },
  speed:     { name: 'Speed lines', params: ['thickness'], draw: (g, o) => { const n = 4, h = 1 / (n * 2 - 1);
    for (let i = 0; i < n; i++) { const y = i * 2 * h, x0 = (i % 2) * 0.12 + i * 0.06;
      poly([[x0 + h, y], [1, y], [1 - h * 2 * o.thickness, y + h], [x0, y + h]])(g); } } },
  swoosh:    { name: 'Swoosh', params: ['thickness'], draw: (g, o) => { g.moveTo(0, 1); g.quadraticCurveTo(0.42, 0.05, 1, 0);
    g.quadraticCurveTo(0.5 + 0.2 * o.thickness, 0.25 + 0.5 * o.thickness, 0, 1); g.closePath(); } },
  wedge:     { name: 'Wedge', draw: poly([[0, 0.35], [1, 0], [1, 1], [0, 0.65]]) },
};
export const SHAPE_DEFAULTS = { shape: 'rect', color: '#e10600', outline: 0, outlineColor: '#000000', radius: 0, thickness: 0.3,
  sides: 6, points: 5, inner: 0.45, slant: 0.3, aspect: 1, custom: null };

/** Draw a shape filling a canvas of the given aspect (width / height). custom = {pts: [[x,y]...], smooth} */
export function renderShape(opts) {
  const o = { ...SHAPE_DEFAULTS, ...opts };
  const L = 1024, aspect = Math.max(0.05, Math.min(20, o.aspect));
  const c = document.createElement('canvas');
  c.width = Math.max(8, Math.round(aspect >= 1 ? L : L * aspect)); c.height = Math.max(8, Math.round(aspect >= 1 ? L / aspect : L));
  const g = c.getContext('2d');
  const ow = o.outline * Math.min(c.width, c.height) * 0.25, pad = ow + 2;
  g.save();
  g.translate(pad, pad); g.scale(c.width - 2 * pad, c.height - 2 * pad);
  g.beginPath();
  if (o.shape === 'custom' && o.custom?.pts?.length > 2) drawCustom(g, o.custom);
  else (SHAPES[o.shape] || SHAPES.rect).draw(g, o);
  g.restore();
  g.fillStyle = o.color; g.fill(SHAPES[o.shape]?.evenodd ? 'evenodd' : 'nonzero');
  if (ow > 0) { g.lineWidth = ow * 2; g.lineJoin = 'round'; g.strokeStyle = o.outlineColor; g.save(); g.clip(SHAPES[o.shape]?.evenodd ? 'evenodd' : 'nonzero'); g.stroke(); g.restore(); }
  return { canvas: c, aspect: c.width / c.height };
}

export function drawCustom(g, { pts, smooth }) {
  if (!smooth) { poly(pts)(g); return; }
  const n = pts.length, mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const m0 = mid(pts[n - 1], pts[0]); g.moveTo(m0[0], m0[1]);
  for (let i = 0; i < n; i++) { const p = pts[i], m = mid(p, pts[(i + 1) % n]); g.quadraticCurveTo(p[0], p[1], m[0], m[1]); }
  g.closePath();
}

// ---- images ------------------------------------------------------------------------------------------
export function toCanvas(img, maxSide = 2048) {
  const w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
  const s = Math.min(1, maxSide / Math.max(w, h));
  const c = document.createElement('canvas'); c.width = Math.max(1, Math.round(w * s)); c.height = Math.max(1, Math.round(h * s));
  c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
  return c;
}

export function loadImage(src) {
  return new Promise((ok, fail) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => fail(new Error('could not read that image')); i.src = src; });
}

/** The colour most of the border has (median per channel). */
export function borderColor(d, w, h) {
  const rs = [], gs = [], bs = [];
  const take = i => { if (d[i + 3] > 200) { rs.push(d[i]); gs.push(d[i + 1]); bs.push(d[i + 2]); } };
  const step = Math.max(1, Math.floor((w + h) / 400));
  for (let x = 0; x < w; x += step) { take(x * 4); take(((h - 1) * w + x) * 4); }
  for (let y = 0; y < h; y += step) { take(y * w * 4); take((y * w + w - 1) * 4); }
  if (!rs.length) return null;
  const med = a => a.sort((p, q) => p - q)[a.length >> 1];
  return [med(rs), med(gs), med(bs)];
}

/** Remove a flat background. mode: auto | white | black | color. tolerance/feather 0..100. Returns a new canvas. */
export function cutout(src, { mode = 'auto', color = '#ffffff', tolerance = 18, feather = 8, connected = true } = {}) {
  const w = src.width, h = src.height;
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(src, 0, 0);
  const img = g.getImageData(0, 0, w, h), d = img.data;
  let bg = mode === 'white' ? [255, 255, 255] : mode === 'black' ? [0, 0, 0]
    : mode === 'color' ? [1, 3, 5].map(i => parseInt(color.slice(i, i + 2), 16)) : borderColor(d, w, h);
  if (!bg) return c;                                          // border already transparent: nothing to do
  const tol = tolerance / 100 * 441, fe = Math.max(1e-3, feather / 100 * 441);
  const dist = new Float32Array(w * h);
  for (let i = 0, p = 0; p < w * h; p++, i += 4) dist[p] = Math.hypot(d[i] - bg[0], d[i + 1] - bg[1], d[i + 2] - bg[2]);
  let region;
  if (connected) {
    region = new Uint8Array(w * h);
    const stack = [];
    const push = p => { if (!region[p] && dist[p] <= tol + fe) { region[p] = 1; stack.push(p); } };
    for (let x = 0; x < w; x++) { push(x); push((h - 1) * w + x); }
    for (let y = 0; y < h; y++) { push(y * w); push(y * w + w - 1); }
    while (stack.length) {
      const p = stack.pop(), x = p % w, y = (p - x) / w;
      if (dist[p] > tol) continue;                            // edge pixels are kept in the region but don't spread
      if (x > 0) push(p - 1); if (x < w - 1) push(p + 1); if (y > 0) push(p - w); if (y < h - 1) push(p + w);
    }
  }
  for (let p = 0, i = 0; p < w * h; p++, i += 4) {
    if (region && !region[p]) continue;
    const t = dist[p] <= tol ? 0 : Math.min(1, (dist[p] - tol) / fe);
    if (t >= 1) continue;
    if (t > 0.02) for (let k = 0; k < 3; k++) d[i + k] = Math.max(0, Math.min(255, (d[i + k] - bg[k] * (1 - t)) / t));   // remove the background tint
    d[i + 3] = Math.round(d[i + 3] * t);
  }
  g.putImageData(img, 0, 0);
  return c;
}

/** Crop away transparent borders. */
export function trim(src, threshold = 8) {
  const w = src.width, h = src.height, d = src.getContext('2d').getImageData(0, 0, w, h).data;
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (d[(y * w + x) * 4 + 3] > threshold) {
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  if (x1 < 0) return src;
  x0 = Math.max(0, x0 - 2); y0 = Math.max(0, y0 - 2); x1 = Math.min(w - 1, x1 + 2); y1 = Math.min(h - 1, y1 + 2);
  if (x0 === 0 && y0 === 0 && x1 === w - 1 && y1 === h - 1) return src;
  const c = document.createElement('canvas'); c.width = x1 - x0 + 1; c.height = y1 - y0 + 1;
  c.getContext('2d').drawImage(src, x0, y0, c.width, c.height, 0, 0, c.width, c.height);
  return c;
}

/** Small alpha map used to tell whether a click landed on the visible part of a decal. */
export function alphaMap(canvas, size = 96) {
  const s = Math.min(1, size / Math.max(canvas.width, canvas.height));
  const w = Math.max(1, Math.round(canvas.width * s)), h = Math.max(1, Math.round(canvas.height * s));
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(canvas, 0, 0, w, h);
  const d = g.getImageData(0, 0, w, h).data, a = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) a[i] = d[i * 4 + 3];
  return { w, h, a, at(u, v) { const x = Math.min(w - 1, Math.max(0, Math.floor(u * w))), y = Math.min(h - 1, Math.max(0, Math.floor(v * h))); return a[y * w + x]; } };
}

// ---- paths (pen tool) ----------------------------------------------------------------------------
// A contour is {closed, pts: [{p: [x, y], i: [x, y] | null, o: [x, y] | null}]}: anchors with optional
// incoming / outgoing Bezier handles, like Photoshop's pen tool.

/** Trace contours into a canvas context. map([x, y]) -> [canvasX, canvasY]. */
export function traceContours(g, contours, map = q => q) {
  for (const c of contours) {
    const pts = c.pts;
    if (!pts.length) continue;
    g.moveTo(...map(pts[0].p));
    const seg = (a, b) => {
      if (!a.o && !b.i) g.lineTo(...map(b.p));
      else g.bezierCurveTo(...map(a.o || a.p), ...map(b.i || b.p), ...map(b.p));
    };
    for (let k = 1; k < pts.length; k++) seg(pts[k - 1], pts[k]);
    if (c.closed && pts.length > 2) { seg(pts[pts.length - 1], pts[0]); g.closePath(); }
  }
}

/** A fake canvas context that records drawing commands as editable contours (cubic Beziers). */
class Recorder {
  constructor() { this.contours = []; this.cur = null; this.pos = null; }
  _start(x, y) { this.cur = { pts: [{ p: [x, y], i: null, o: null }], closed: false }; this.contours.push(this.cur); this.pos = [x, y]; }
  moveTo(x, y) { this._start(x, y); }
  lineTo(x, y) {
    if (!this.cur) { if (this.pos) this._start(...this.pos); else return this._start(x, y); }
    const l = this.cur.pts.at(-1).p;
    if (Math.hypot(l[0] - x, l[1] - y) > 1e-9) this.cur.pts.push({ p: [x, y], i: null, o: null });
    this.pos = [x, y];
  }
  bezierCurveTo(a, b, c, d, x, y) {
    if (!this.cur) this._start(...(this.pos || [a, b]));
    this.cur.pts.at(-1).o = [a, b];
    this.cur.pts.push({ p: [x, y], i: [c, d], o: null }); this.pos = [x, y];
  }
  quadraticCurveTo(cx, cy, x, y) {
    const [px, py] = this.pos || [cx, cy];
    this.bezierCurveTo(px + 2 / 3 * (cx - px), py + 2 / 3 * (cy - py), x + 2 / 3 * (cx - x), y + 2 / 3 * (cy - y), x, y);
  }
  closePath() {
    if (!this.cur) return;
    const pts = this.cur.pts, f = pts[0], l = pts.at(-1);
    if (pts.length > 1 && Math.hypot(f.p[0] - l.p[0], f.p[1] - l.p[1]) < 1e-6) { f.i = l.i; pts.pop(); }
    this.cur.closed = true; this.pos = f.p; this.cur = null;
  }
  rect(x, y, w, h) { this.moveTo(x, y); this.lineTo(x + w, y); this.lineTo(x + w, y + h); this.lineTo(x, y + h); this.closePath(); }
  ellipse(cx, cy, rx, ry, _rot, a0, a1, ccw = false) {
    let sweep = a1 - a0;
    if (!ccw) { while (sweep < 0) sweep += Math.PI * 2; } else { while (sweep > 0) sweep -= Math.PI * 2; }
    if (Math.abs(a1 - a0) >= Math.PI * 2 - 1e-9) sweep = ccw ? -Math.PI * 2 : Math.PI * 2;
    const P = t => [cx + rx * Math.cos(t), cy + ry * Math.sin(t)], T = t => [-rx * Math.sin(t), ry * Math.cos(t)];
    const s = P(a0);
    if (this.cur) this.lineTo(...s); else this._start(...s);
    const n = Math.max(1, Math.ceil(Math.abs(sweep) / (Math.PI / 2) - 1e-9)), d = sweep / n, k = 4 / 3 * Math.tan(d / 4);
    for (let i = 0; i < n; i++) {
      const t1 = a0 + i * d, t2 = t1 + d, p1 = P(t1), p2 = P(t2), v1 = T(t1), v2 = T(t2);
      this.bezierCurveTo(p1[0] + k * v1[0], p1[1] + k * v1[1], p2[0] - k * v2[0], p2[1] - k * v2[1], ...p2);
    }
  }
  arc(x, y, r, a0, a1, ccw) { this.ellipse(x, y, r, r, 0, a0, a1, ccw); }
  arcTo(x1, y1, x2, y2, r) {
    const [x0, y0] = this.pos || [x1, y1];
    const v1 = [x0 - x1, y0 - y1], v2 = [x2 - x1, y2 - y1], l1 = Math.hypot(...v1), l2 = Math.hypot(...v2);
    if (r <= 1e-9 || l1 < 1e-9 || l2 < 1e-9) return this.lineTo(x1, y1);
    v1[0] /= l1; v1[1] /= l1; v2[0] /= l2; v2[1] /= l2;
    const th = Math.acos(Math.max(-1, Math.min(1, v1[0] * v2[0] + v1[1] * v2[1])));
    if (th < 1e-4 || Math.abs(th - Math.PI) < 1e-4) return this.lineTo(x1, y1);
    const d = r / Math.tan(th / 2), h = 4 / 3 * Math.tan((Math.PI - th) / 4) * r;
    const t1 = [x1 + v1[0] * d, y1 + v1[1] * d], t2 = [x1 + v2[0] * d, y1 + v2[1] * d];
    this.lineTo(...t1);
    this.bezierCurveTo(t1[0] - v1[0] * h, t1[1] - v1[1] * h, t2[0] - v2[0] * h, t2[1] - v2[1] * h, ...t2);
  }
  // transforms are not used by the shape definitions (they draw in the unit box)
  save() {} restore() {} translate() {} scale() {} beginPath() {}
}

/** Editable contours (unit box, y down) for a shape from SHAPES or a custom polygon. */
export function shapeContours(opts) {
  const o = { ...SHAPE_DEFAULTS, ...opts }, rec = new Recorder();
  if (o.shape === 'custom' && o.custom?.pts?.length > 2) drawCustom(rec, o.custom);
  else (SHAPES[o.shape] || SHAPES.rect).draw(rec, o);
  return { contours: rec.contours.filter(c => c.pts.length > 1), evenodd: !!SHAPES[o.shape]?.evenodd };
}
