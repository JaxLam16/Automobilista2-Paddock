/* Pure replay timing: signed gaps at the same cumulative race distance, including lapped cars. */
(function (root) {
  "use strict";
  function sample(a, t, timing) {
    var f = (t - timing.t0) / timing.dt, i = Math.floor(f), last = a.length - 1;
    if (i < 0 || i > last) return NaN;
    if (i === last || f === i) return a[i];
    if (!Number.isFinite(a[i]) || !Number.isFinite(a[i + 1])) return NaN;
    return a[i] + (a[i + 1] - a[i]) * (f - i);
  }
  function timeAt(c, distance, maxIndex, timing) {
    var dm = c.dmax, lo = 0, hi = Math.min(maxIndex, dm.length - 1);
    if (!Number.isFinite(distance) || hi < 0 || !(dm[hi] >= distance) || distance < dm[0]) return null;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (dm[mid] >= distance) hi = mid; else lo = mid + 1;
    }
    if (lo === 0) return timing.t0;
    var a = dm[lo - 1], b = dm[lo];
    if (!Number.isFinite(a) || !Number.isFinite(b) || !Number.isFinite(c.dist[lo - 1]) || !Number.isFinite(c.dist[lo])) return null;
    return timing.t0 + (lo - 1 + (b > a ? (distance - a) / (b - a) : 0)) * timing.dt;
  }
  function gapAt(reference, other, t, timing) {
    var a = sample(reference.dist, t, timing), b = sample(other.dist, t, timing);
    if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
    var distance = Math.min(a, b), last = Math.ceil((t - timing.t0) / timing.dt);
    var ta = timeAt(reference, distance, last, timing), tb = timeAt(other, distance, last, timing);
    return ta == null || tb == null ? null : tb - ta;  // positive: other car is behind the reference
  }
  var api = {sample: sample, timeAt: timeAt, gapAt: gapAt};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.AMS2ReplayTiming = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
