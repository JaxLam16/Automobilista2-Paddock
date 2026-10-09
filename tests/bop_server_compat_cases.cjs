'use strict';
// Exercise the real control renderer with old/new server payloads on both pages.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ams2season/bop_editor.js'), 'utf8');
const anchor = '  function carSetupControls() {';
assert.equal(source.split(anchor).length, 2);
const instrumented = source.replace(anchor,
  '  window.compatRenderers.push(function(data) { B.data = data; return carSetupControls(); });\n' + anchor);
const context = {
  window: {compatRenderers: []},
  h: (tag, attrs, ...children) => ({tag, attrs, children}),
};
vm.runInNewContext(instrumented, context, {filename: 'bop_editor.js'});
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (tree && typeof tree === 'object') return [tree, ...tree.children.flatMap(nodes)];
  return [];
}
function words(tree) {
  if (Array.isArray(tree)) return tree.map(words).join(' ');
  return tree && typeof tree === 'object' ? tree.children.map(words).join(' ') : String(tree ?? '');
}
assert.equal(context.window.compatRenderers.length, 2);
for (const render of context.window.compatRenderers) {
  for (const stale of [{}, {car_setups: null}]) {
    const result = render(stale);
    assert.match(words(result), /background server.*older version/);
    assert.match(words(result), /wait 20 seconds/);
    assert.match(words(result), /Finish any recording/);
    assert.equal(nodes(result).filter(n => ['button', 'input', 'select'].includes(n.tag)).length, 0);
  }
  const result = render({car_setups: []});
  assert.doesNotMatch(words(result), /background server/);
  const buttons = nodes(result).filter(n => n.tag === 'button');
  assert.deepEqual(buttons.map(words), ['Save car setup', 'Load car setup', 'Export car setup', 'Import car setup']);
  assert.equal(buttons[0].attrs.disabled, undefined);
  assert.equal(buttons[1].attrs.disabled, true);
  assert.equal(buttons[2].attrs.disabled, true);
  assert.equal(buttons[3].attrs.disabled, undefined);
}
process.stdout.write('Both pages: stale servers show restart instructions; current empty catalogs keep Save/Import usable.\n');
