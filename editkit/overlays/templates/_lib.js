// Shared helpers for overlay templates. Every template is a pure function of time:
// window.seek(t) must draw the exact state at t seconds, so frames render deterministically.
const E = {
  linear: t => t,
  inCubic: t => t * t * t,
  outCubic: t => 1 - Math.pow(1 - t, 3),
  outQuint: t => 1 - Math.pow(1 - t, 5),
  inOutCubic: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  outExpo: t => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)),
  outBack: t => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
  outElastic: t => (t === 0 || t === 1 ? t : Math.pow(2, -10 * t) * Math.sin((t * 10 - 0.75) * (2 * Math.PI) / 3) + 1),
};
const clamp01 = x => Math.max(0, Math.min(1, x));
const lerp = (a, b, t) => a + (b - a) * t;
// eased 0..1 progress of a window that starts at `a` and lasts `d` seconds
const win = (t, a, d, ease = 'outCubic') => E[ease](clamp01((t - a) / d));
const P = Object.assign({}, window.DEFAULTS || {}, window.PARAMS || {});
const DUR = window.DURATION || 3;
const W = window.W || 1080, H = window.H || 1920;
const U = Math.min(W, H) / 1080; // 1 unit = 1px at 1080 short edge
// exit factor: 1 while on screen, eases to 0 over the last `d` seconds
const exitK = (t, d = 0.45) => 1 - E.inCubic(clamp01((t - (DUR - d)) / d));
function css(el, o) { for (const k in o) el.style[k] = o[k]; }
function fmtNum(n, decimals = 0) { return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }); }
document.documentElement.style.setProperty('--u', U + 'px');
document.documentElement.style.setProperty('--accent', P.accent || '#d9b36c');
document.documentElement.style.setProperty('--ink', P.ink || '#ffffff');
