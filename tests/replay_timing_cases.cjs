const assert = require('node:assert/strict');
const timing = require('../ams2season/replay_timing.js');
const clock = {t0: 0, dt: 1};
function car(speed) {
  const dist = Array.from({length: 201}, (_, i) => i * speed);
  return {dist, dmax: dist.slice()};
}
const a = car(20), b = car(10);
assert.equal(timing.gapAt(a, b, 80, clock), 40);
assert.equal(timing.gapAt(b, a, 80, clock), -40);
assert.equal(timing.gapAt(a, a, 80, clock), 0);
assert.equal(timing.gapAt(a, b, 80.5, clock), 40.25);
// Full cumulative distance: lapping cannot wrap a 40 s gap down to zero.
assert.equal(timing.timeAt(a, 800, 80, clock), 40);
assert.equal(timing.timeAt(a, 2000, 80, clock), null); // future progress is unavailable
const missing = car(10); missing.dist[80] = NaN;
assert.equal(timing.gapAt(a, missing, 80, clock), null);
assert.equal(timing.gapAt(a, missing, 79.5, clock), null);
assert.equal(timing.sample(missing.dist, 79, clock), 790); // exact valid sample before a gap
const late = car(10); late.dist = late.dist.map(d => d + 100); late.dmax = late.dist.slice();
assert.equal(timing.gapAt(a, late, 0, clock), null); // no shared starting distance
console.log('Replay timing cases passed.');
