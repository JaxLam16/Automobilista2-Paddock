/* This page uses the app's existing helpers and keeps its own state. */
(function () {
  'use strict';
  var L = {data: null, drafts: {}, selected: null, query: '', cls: '', liveryQuery: '', show: 'all', busy: false, preset: ''};
  function ids(car) { return L.drafts[car.id] || car.enabled.slice(); }
  function same(a, b) { return a.length === b.length && a.every(function (x) { return b.indexOf(x) >= 0; }); }
  function changed(car) { return !same(ids(car), car.enabled) || car.needs_sync; }
  function touched() {
    var result = {};
    (L.data ? L.data.cars : []).forEach(function (c) { if (c.editable && L.drafts[c.id]) result[c.id] = ids(c).slice(); });
    return result;
  }
  function changes() {
    var result = {};
    (L.data ? L.data.cars : []).forEach(function (c) {
      if (c.editable && L.drafts[c.id] && changed(c)) result[c.id] = ids(c).slice();
    });
    return result;
  }
  function modal(title) {
    var dlg = h('dialog', {class: 'lv-dialog'}, h('h2', null, title));
    document.body.appendChild(dlg);
    dlg.addEventListener('close', function () { dlg.remove(); });
    return dlg;
  }
  function setBusy(value, message) {
    L.busy = value;
    document.querySelectorAll('.livery-editor button, .livery-editor input, .livery-editor select').forEach(function (b) { b.disabled = value; });
    var status = document.getElementById('lv-status');
    if (status) { status.textContent = message || ''; status.classList.remove('error'); }
  }
  function failure(e) {
    setBusy(false);
    var status = document.getElementById('lv-status');
    if (status) { status.textContent = e.message || String(e); status.classList.add('error'); }
    draw();
    fail(e);
  }
  function adopt(data, reset) {
    L.data = data;
    if (reset) L.drafts = {};
    if (!data.cars.some(function (c) { return c.id === L.selected; })) L.selected = data.cars.length ? data.cars[0].id : null;
    if (L.selected && !L.drafts[L.selected]) L.drafts[L.selected] = data.cars.find(function (c) { return c.id === L.selected; }).enabled.slice();
    setBusy(false);
    draw();
  }
  function reload(reset) { return api('/api/liveries').then(function (data) { adopt(data, reset); }); }
  function filtered() {
    return L.data.cars.filter(function (c) {
      return (!L.cls || c.class === L.cls) && (!L.query || (c.name + ' ' + c.class + ' ' + c.id).toLowerCase().indexOf(L.query.toLowerCase()) >= 0);
    });
  }
  function drawCars() {
    var box = document.getElementById('lv-car-list');
    if (!box || !L.data) return;
    var cars = filtered();
    fill(box, cars.length ? cars.map(function (c) {
      return h('button', {class: 'lv-car', 'aria-pressed': String(c.id === L.selected), onclick: function () {
        L.selected = c.id;
        if (!L.drafts[c.id]) L.drafts[c.id] = c.enabled.slice();
        drawCars(); drawDetail(); drawFooter();
      }}, h('span', {class: 'lv-car-title'}, c.name, changed(c) && L.drafts[c.id] ? h('span', {class: 'lv-draft-dot', title: 'Unapplied changes'}) : null),
      h('span', {class: 'lv-car-meta'}, h('span', null, c.class), h('span', {class: 'lv-count'}, ids(c).length + '/' + c.total)));
    }) : h('p', {class: 'muted'}, 'No matching cars.'));
    var count = document.getElementById('lv-car-count');
    if (count) count.textContent = cars.length + (cars.length === 1 ? ' car' : ' cars');
  }
  function drawGrid(car) {
    var grid = document.getElementById('lv-grid');
    if (!grid) return;
    var kept = ids(car);
    var rows = car.liveries.filter(function (e) {
      var on = kept.indexOf(e.id) >= 0;
      return (!L.liveryQuery || (e.name + ' ' + e.id).toLowerCase().indexOf(L.liveryQuery.toLowerCase()) >= 0)
        && (L.show === 'all' || (L.show === 'enabled' ? on : !on));
    });
    fill(grid, rows.length ? rows.map(function (e) {
      var on = kept.indexOf(e.id) >= 0;
      var card = h('label', {class: 'lv-card ' + (on ? 'on' : 'off')});
      var status = h('span', {class: 'lv-card-status'}, 'ID ' + e.id + ' · ' + (on ? 'Enabled' : 'Disabled'));
      var cb = h('input', {class: 'lv-check', type: 'checkbox', checked: on, disabled: !car.editable || L.busy,
        'aria-label': 'Enable ' + e.name, onchange: function () {
          var list = ids(car).slice(), pos = list.indexOf(e.id);
          if (cb.checked && pos < 0) list.push(e.id);
          if (!cb.checked && pos >= 0) list.splice(pos, 1);
          L.drafts[car.id] = list;
          card.classList.toggle('on', cb.checked); card.classList.toggle('off', !cb.checked);
          status.textContent = 'ID ' + e.id + ' · ' + (cb.checked ? 'Enabled' : 'Disabled');
          drawCars(); drawFooter();
          if (L.show !== 'all') drawGrid(car);
        }});
      var imageBox = h('div', {class: 'lv-image'});
      var img = h('img', {loading: 'lazy', alt: e.name, src: '/api/liveries/image?car=' + encodeURIComponent(car.id) + '&livery=' + encodeURIComponent(e.id),
        onerror: function () { fill(imageBox, h('span', {class: 'lv-placeholder'}, h('b', null, '#' + e.id), 'Preview unavailable')); }});
      imageBox.appendChild(img);
      fill(card, cb, imageBox, h('span', {class: 'lv-card-text'}, h('span', {class: 'lv-card-name'}, e.name), status));
      return card;
    }) : h('p', {class: 'muted'}, 'No matching liveries.'));
  }
  function drawDetail() {
    var box = document.getElementById('lv-detail');
    if (!box || !L.data) return;
    var car = L.data.cars.find(function (c) { return c.id === L.selected; });
    if (!car) { fill(box, h('div', {class: 'panel pad'}, h('h2', null, 'Choose a car'), h('p', {class: 'lv-note'}, 'Scan your game folder to load the installed liveries.'))); return; }
    var search = h('input', {type: 'search', placeholder: 'Search livery name or ID', value: L.liveryQuery, 'aria-label': 'Search liveries',
      oninput: function () { L.liveryQuery = search.value; drawGrid(car); }});
    var show = h('select', {'aria-label': 'Show liveries', onchange: function () { L.show = show.value; drawGrid(car); }},
      [['all', 'All liveries'], ['enabled', 'Enabled'], ['disabled', 'Disabled']].map(function (x) { return h('option', {value: x[0], selected: x[0] === L.show}, x[1]); }));
    function setAll(values) { L.drafts[car.id] = values; drawGrid(car); drawCars(); drawFooter(); }
    fill(box,
      h('div', {class: 'lv-detail-head'}, h('div', null, h('span', {class: 'badge'}, car.class), h('h2', null, car.name)), h('span', {class: 'badge'}, car.total + ' liveries')),
      !car.editable ? h('div', {class: 'lv-error'}, 'This car is read-only. ' + car.errors.join(' ')) : null,
      h('div', {class: 'lv-controls'},
        h('button', {class: 'btn ghost small', disabled: !car.editable, onclick: function () { setAll(car.liveries.map(function (e) { return e.id; })); }}, 'Enable all'),
        h('button', {class: 'btn ghost small', disabled: !car.editable, onclick: function () { setAll([]); }}, 'Disable all'),
        h('button', {class: 'btn ghost small', onclick: function () { setAll(car.enabled.slice()); }}, 'Reset this car')),
      h('div', {class: 'lv-search-row'}, search, show), h('div', {class: 'lv-grid', id: 'lv-grid'}));
    drawGrid(car);
  }
  function drawFooter() {
    var box = document.getElementById('lv-footer');
    if (!box || !L.data) return;
    var dirty = changes(), n = Object.keys(dirty).length, invalid = Object.keys(dirty).some(function (k) { return dirty[k].length === 0; });
    var count = Object.keys(dirty).reduce(function (sum, k) { return sum + dirty[k].length; }, 0);
    var car = L.data.cars.find(function (c) { return c.id === L.selected; });
    fill(box, h('div', null, h('strong', null, n ? n + (n === 1 ? ' car' : ' cars') + ' with unapplied changes' : 'Your selections match the game'),
      h('p', {class: 'lv-note'}, invalid ? 'Keep at least one livery enabled for every car.' : n ? count + ' liveries will remain enabled across those cars.' : car ? ids(car).length + ' of ' + car.total + ' enabled for this car.' : 'Choose a car to begin.')),
      h('button', {class: 'btn', id: 'lv-review', disabled: !n || invalid || L.busy, onclick: review}, 'Review changes'));
  }
  function draw() {
    if (!L.data || !document.getElementById('lv-workspace')) return;
    var workspace = document.getElementById('lv-workspace');
    var cls = h('select', {'aria-label': 'Filter car class', onchange: function () { L.cls = cls.value; drawCars(); }},
      h('option', {value: '', selected: !L.cls}, 'All classes'),
      Array.from(new Set(L.data.cars.map(function (c) { return c.class; }))).sort().map(function (c) { return h('option', {value: c, selected: c === L.cls}, c); }));
    var carSearch = h('input', {class: 'lv-car-search', type: 'search', placeholder: 'Search cars', value: L.query, 'aria-label': 'Search cars', oninput: function () { L.query = carSearch.value; drawCars(); }});
    var preset = h('select', {'aria-label': 'League preset', onchange: function () { L.preset = preset.value; }},
      h('option', {value: ''}, 'Choose a league preset'), L.data.presets.map(function (p) { return h('option', {value: p.id, selected: p.id === L.preset}, p.name + ' (' + p.cars + ' cars)'); }));
    var importInput = h('input', {type: 'file', accept: '.json,application/json', hidden: true, onchange: function () {
      var file = importInput.files[0]; if (!file) return;
      if (file.size > 1024 * 1024) return fail(new Error('Choose a preset smaller than 1 MB.'));
      file.text().then(function (text) {
        var data = JSON.parse(text);
        if (data.format !== 'ams2season-liveries' || data.version !== 1) throw new Error('This is not an AMS2 Season livery preset.');
        return api('/api/liveries/presets', 'POST', data).then(function (r) { L.preset = r.id; return reload(false); });
      }).then(function () { toast('Preset imported. Load it to stage its selections.'); }).catch(fail);
    }});
    fill(workspace,
      h('div', {class: 'lv-toolbar'}, preset,
        h('button', {class: 'btn ghost small', onclick: loadPreset}, 'Load preset'),
        h('button', {class: 'btn ghost small', onclick: savePreset}, 'Save preset'),
        h('button', {class: 'btn ghost small', onclick: exportPreset}, 'Export'),
        h('button', {class: 'btn ghost small', onclick: function () { importInput.click(); }}, 'Import'), importInput,
        h('span', {class: 'lv-grow'}),
        h('button', {class: 'btn ghost small', disabled: !L.data.can_undo || L.busy, onclick: undo}, 'Undo last apply')),
      h('div', {class: 'lv-layout'}, h('section', {class: 'panel lv-list', 'aria-label': 'Installed cars'},
        h('div', {class: 'headrow'}, h('h3', null, 'Installed cars'), h('span', {class: 'badge', id: 'lv-car-count'})), carSearch, cls,
        h('div', {class: 'lv-car-list', id: 'lv-car-list'})), h('section', {id: 'lv-detail', 'aria-label': 'Livery selections'})),
      h('div', {class: 'lv-footer', id: 'lv-footer'}),
      L.data.issues.length ? h('details', {class: 'lv-issues'}, h('summary', null, L.data.issues.length + ' packages could not be read'),
        h('ul', null, L.data.issues.map(function (e) { return h('li', null, e.file + ': ' + e.message); }))) : null,
      h('p', {class: 'lv-note'}, 'Selections apply to this game installation. Disabled liveries stay in the saved catalog so you can enable them again.'));
    drawCars(); drawDetail(); drawFooter();
    if (L.busy) document.querySelectorAll('.livery-editor button, .livery-editor input, .livery-editor select').forEach(function (b) { b.disabled = true; });
  }
  function review() {
    setBusy(true, 'Preparing your changes…');
    api('/api/liveries/preview', 'POST', {selections: changes()}).then(function (plan) {
      setBusy(false); draw();
      var dlg = modal('Review livery selections');
      var apply = h('button', {class: 'btn', disabled: !plan.count, onclick: function () {
        apply.disabled = true; cancel.disabled = true; apply.textContent = 'Applying…';
        api('/api/liveries/apply', 'POST', {token: plan.token}).then(function (result) {
          dlg.close(); return reload(true).then(function () {
            var status = document.getElementById('lv-status');
            if (status) status.textContent = result.changed ? 'Applied. Start AMS2 to see your selections. Backup: ' + result.backup : result.message;
            toast(result.changed ? 'Livery selections applied.' : result.message);
          });
        }).catch(function (e) { dlg.close(); failure(e); });
      }}, 'Apply to game');
      var cancel = h('button', {class: 'btn ghost', onclick: function () { dlg.close(); }}, 'Cancel');
      dlg.appendChild(h('p', {class: 'lv-note'}, 'Close AMS2 and your content manager before applying. A backup is created for every changed file.'));
      dlg.appendChild(h('table', null, h('thead', null, h('tr', null, h('th', null, 'Car'), h('th', {class: 'num'}, 'Now'), h('th', {class: 'num'}, 'After apply'))),
        h('tbody', null, plan.cars.map(function (c) { return h('tr', null, h('td', null, c.name), h('td', {class: 'num'}, c.before), h('td', {class: 'num'}, c.after)); }))));
      dlg.appendChild(h('details', null, h('summary', null, plan.count + ' game files will be updated'), h('ul', null, plan.files.map(function (f) { return h('li', null, f.path); }))));
      dlg.appendChild(h('div', {class: 'actions'}, cancel, apply));
      dlg.showModal();
    }).catch(failure);
  }
  function savePreset() {
    var selections = touched();
    if (!Object.keys(selections).length) return fail(new Error('Choose a car and its liveries first.'));
    var dlg = modal('Save league preset');
    var input = h('input', {type: 'text', maxlength: 80, placeholder: 'GT3 Gen 0 league', 'aria-label': 'Preset name'});
    var save = h('button', {class: 'btn', onclick: function () {
      save.disabled = true;
      api('/api/liveries/presets', 'POST', {name: input.value, selections: selections}).then(function (r) {
        L.preset = r.id; dlg.close(); return reload(false);
      }).then(function () { toast('League preset saved.'); }).catch(function (e) { save.disabled = false; fail(e); });
    }}, 'Save preset');
    dlg.appendChild(h('p', {class: 'lv-note'}, 'Save the current selections for ' + Object.keys(selections).length + ' cars. Saving a preset does not change the game.'));
    dlg.appendChild(input);
    dlg.appendChild(h('div', {class: 'actions'}, h('button', {class: 'btn ghost', onclick: function () { dlg.close(); }}, 'Cancel'), save));
    dlg.showModal(); input.focus();
  }
  function loadPreset() {
    if (!L.preset) return fail(new Error('Choose a saved preset first.'));
    api('/api/liveries/preset?id=' + encodeURIComponent(L.preset)).then(function (preset) {
      var lookup = {}; L.data.cars.forEach(function (c) { lookup[c.id] = c; });
      Object.keys(preset.selections).forEach(function (id) {
        var c = lookup[id];
        if (!c || preset.selections[id].some(function (value) { return !c.liveries.some(function (e) { return e.id === String(value); }); }))
          throw new Error('This preset includes unavailable cars or liveries. Rescan after installing the same mods.');
      });
      Object.keys(preset.selections).forEach(function (id) { L.drafts[id] = preset.selections[id].map(String); });
      L.selected = Object.keys(preset.selections)[0] || L.selected; draw(); toast('Preset loaded. Review changes to apply it.');
    }).catch(fail);
  }
  function exportPreset() {
    if (!L.preset) return fail(new Error('Choose a saved preset to export.'));
    api('/api/liveries/preset?id=' + encodeURIComponent(L.preset)).then(function (data) {
      var url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
      var a = h('a', {href: url, download: data.name.replace(/[^\w-]+/g, '-') + '.json'}); a.click();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }).catch(fail);
  }
  function undo() {
    setBusy(true, 'Restoring the last livery apply…');
    api('/api/liveries/undo', 'POST', {}).then(function () { return reload(true); }).then(function () {
      toast('The last livery apply was undone.');
      var s = document.getElementById('lv-status'); if (s) s.textContent = 'Restored. Start AMS2 to see the previous selections.';
    }).catch(failure);
  }
  window.viewLiveries = function () {
    var path = h('input', {type: 'text', id: 'lv-game-path', placeholder: 'J:\\SteamLibrary\\steamapps\\common\\Automobilista 2', 'aria-label': 'Automobilista 2 installation folder'});
    var scan = h('button', {class: 'btn', id: 'lv-scan', onclick: function () {
      setBusy(true, 'Reading installed cars and liveries…');
      api('/api/liveries/scan', 'POST', {game_path: path.value}).then(function (data) {
        adopt(data, true); path.value = data.game_path;
        document.getElementById('lv-status').textContent = data.cars.length + (data.cars.length === 1 ? ' car loaded.' : ' cars loaded.') + ' Choose a car to edit its liveries.';
      }).catch(failure);
    }}, 'Scan game');
    var page = h('div', {class: 'livery-editor'}, h('h1', null, 'Livery editor'),
      h('p', {class: 'lv-subtitle'}, 'Choose which liveries appear in AMS2, then save the selections for your league.'),
      h('div', {class: 'panel pad'}, h('div', {class: 'lv-setup'}, h('div', {class: 'lv-path-field'}, h('label', {class: 'lv-caption', for: 'lv-game-path'}, 'Automobilista 2 folder'), path), scan),
        h('p', {class: 'lv-note'}, 'Scanning reads the installed files. Review changes when you are ready to apply your selection.'), h('p', {class: 'lv-status', id: 'lv-status', role: 'status'})),
      h('div', {id: 'lv-workspace'}));
    var originalPath = h('input', {type: 'text', placeholder: 'Full path to your original BFF or RCF', 'aria-label': 'Original livery catalog file'});
    page.appendChild(h('details', {class: 'lv-issues'}, h('summary', null, 'Recover liveries restricted before using this editor'),
      h('p', {class: 'lv-note'}, 'Scan the game first, then import a saved original BFF or RCF. This restores the editor’s catalog without changing your game selection.'),
      h('div', {class: 'lv-setup', style: {marginTop: '12px'}}, h('div', {class: 'lv-path-field'}, originalPath),
        h('button', {class: 'btn ghost', onclick: function () {
          setBusy(true, 'Reading the original livery catalog…');
          api('/api/liveries/catalog-import', 'POST', {original_path: originalPath.value}).then(function (data) {
            adopt(data, true);
            document.getElementById('lv-status').textContent = 'Original catalog imported for ' + data.imported_cars + (data.imported_cars === 1 ? ' car.' : ' cars.') + ' The game selection is unchanged.';
          }).catch(failure);
        }}, 'Import original catalog'))));
    setView(page);
    return api('/api/liveries/config').then(function (config) {
      path.value = config.game_path || config.suggestions[0] || '';
      if (config.scanned) return reload(false);
      if (L.data) { L.data = null; L.drafts = {}; }
      fill(document.getElementById('lv-workspace'), h('div', {class: 'panel pad', style: {marginTop: '22px'}},
        h('h2', null, 'Load your installed liveries'), h('p', {class: 'lv-note'}, 'Enter the game folder above and select Scan game.')));
    });
  };
}());
