/* Additive page: uses the existing app helpers, keeps all BOP state private. */
(function () {
  'use strict';
  var conversionHandoff = [];
  var conversionHandoffSelection = '';
  function createEditor(converting) {
  var B = {data: null, selected: '', filter: '', search: '', target: '', detail: {}, drafts: {},
    panel: converting ? 'convert' : 'compare', busy: false, comparison: null, proposal: null, strength: 60,
    axes: {mass: true, power_to_weight: true}, group: '', grid: '', custom: false,
    profile: '', carSetup: '', recordings: null, measured: null, recording: '', generation: 0,
    columns: ['mass', 'power_hp', 'power_to_weight', 'peak_torque', 'rev_limit', 'body_drag', 'wing_lift'],
    evaluated: {}, evalErrors: {}, evalTimer: null, conversionInfo: null, reference: '',
    modules: {mass:true, power:true, tyres:true, wings:true, underbody:true, suspension:true, roll_control:false, ride_height:true, brakes:true, inertia:true},
    moveClass:true, performanceTarget:'class', inertiaMass:null, conversionMode:'donor', donorInfo:null,
    donor:'', donorSources:{}, donorBaseline:'', donorOffsets:{power:0,aero:0,braking:0,cornering:0}};
  if (converting) B.strength = 100;
  var storageKey = converting ? 'ams2season.conversion.drafts' : 'ams2season.bop.drafts';
  var carSetupRestartMessage = 'Paddock’s background server is running an older version that does not support car setups. Finish any recording, close all Paddock windows, wait 20 seconds, then reopen Paddock. Refreshing the page does not restart the server.';
  function here() { return location.hash.split('?')[0] === (converting ? '#/conversion' : '#/bop'); }
  function car() { return B.data && B.data.cars.find(function (c) { return c.id === B.selected; }); }
  function detail() { return B.detail[B.selected]; }
  function metric(id) { return B.data.metrics.find(function (m) { return m.id === id; }); }
  function f(value, id) {
    if (value == null || !isFinite(value)) return 'Unavailable';
    var digits = ['body_drag', 'wing_lift', 'cg_height', 'engine_inertia', 'first_gear_ratio', 'top_gear_ratio', 'final_drive_ratio'].indexOf(id) >= 0 || /_(ride_height|bump_travel|rebound_travel)$/.test(id) ? 3 :
      id === 'rear_weight_share' ? 1 : ['mass', 'rev_limit', 'forward_gears'].indexOf(id) >= 0 ? 0 : 1;
    return (id === 'rear_weight_share' ? value * 100 : value).toLocaleString(undefined, {maximumFractionDigits: digits});
  }
  function unit(id) { return id === 'rear_weight_share' ? '%' : metric(id).unit; }
  function edits() {
    return Object.keys(B.drafts).filter(function (id) {
      var d = B.drafts[id];
      return Object.keys(d.parameters || {}).length || d.target_class != null || d.tyres != null || d.donor_baseline;
    }).map(function (id) { return B.drafts[id]; });
  }
  function draft() {
    if (!B.drafts[B.selected]) B.drafts[B.selected] = {car: B.selected, fingerprint: car().fingerprint, parameters: {}};
    return B.drafts[B.selected];
  }
  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify({game: B.data.game_path, edits: edits()})); } catch (_) {}
  }
  function updateMetrics(id, delay) {
    clearTimeout(B.evalTimer);
    B.evalTimer = setTimeout(function () {
      var request = B.drafts[id]; if (!request) return;
      var snapshot = JSON.stringify(request);
      api('/api/bop/evaluate', 'POST', JSON.parse(snapshot)).then(function (result) {
        if (JSON.stringify(B.drafts[id]) !== snapshot) return;
        B.evaluated[id] = {key: snapshot, after: result.after}; delete B.evalErrors[id];
        renderStats(); footer();
      }).catch(function (error) {
        if (JSON.stringify(B.drafts[id]) !== snapshot) return;
        B.evalErrors[id] = error.message; renderStats(); footer();
      });
    }, delay == null ? 250 : delay);
  }
  function renderStats() {
    if (!here()) return;
    var el = document.getElementById('bop-stats');
    if (el && detail()) el.replaceWith(infoCards());
  }
  function restore() {
    try {
      var legacy = JSON.parse(localStorage.getItem('ams2season.bop.drafts') || 'null');
      if (legacy && legacy.game === B.data.game_path && Array.isArray(legacy.edits)) {
        var moved = legacy.edits.filter(classEdit);
        if (moved.length) {
          handoff(moved);
          legacy.edits = legacy.edits.filter(function(d) {return !classEdit(d);});
          localStorage.setItem('ams2season.bop.drafts', JSON.stringify(legacy));
        }
      }
      var saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
      if (saved && saved.game === B.data.game_path) saved.edits.forEach(function (d) {
        var c = B.data.cars.find(function (x) { return x.id === d.car; });
        if (c && c.fingerprint === d.fingerprint) B.drafts[d.car] = d;
      });
      if (converting) {
        conversionHandoff.forEach(function(d) {var c=B.data.cars.find(function(x) {return x.id===d.car;}); if(c && c.fingerprint===d.fingerprint) B.drafts[d.car]=d;});
        conversionHandoff=[];
        if (conversionHandoffSelection && B.data.cars.some(function (c) { return c.id === conversionHandoffSelection; })) B.selected = conversionHandoffSelection;
        conversionHandoffSelection = '';
        var staged=B.drafts[B.selected];
        if(staged && staged.target_class) {B.target=staged.target_class;B.custom=!B.data.classes.some(function(c) {return c.id===B.target;});B.group=staged.group || car().group;B.grid=staged.grid || car().grid;}
      }
    } catch (_) {}
  }
  function classEdit(d) {
    var c=B.data.cars.find(function(x) {return x.id===d.car;});
    return !!c && (d.donor_baseline || d.target_class != null && d.target_class !== c.class || d.group != null && d.group !== c.group || d.grid != null && d.grid !== c.grid);
  }
  function handoff(edits) {
    conversionHandoff=conversionHandoff.concat(edits);
    try {
      var saved=JSON.parse(localStorage.getItem('ams2season.conversion.drafts') || 'null');
      var combined={};
      if(saved && saved.game===B.data.game_path) saved.edits.forEach(function(d) {combined[d.car]=d;});
      edits.forEach(function(d) {combined[d.car]=d;});
      localStorage.setItem('ams2season.conversion.drafts',JSON.stringify({game:B.data.game_path,edits:Object.values(combined)}));
    } catch (_) {}
  }
  function setBusy(value, message) {
    B.busy = value;
    if (!here()) return;
    document.querySelectorAll('.bop-editor button, .bop-editor input, .bop-editor select').forEach(function (el) {
      if (value) { if (el.dataset.bopDisabled == null) el.dataset.bopDisabled = el.disabled ? '1' : '0'; el.disabled = true; }
      else if (el.dataset.bopDisabled != null) { el.disabled = el.dataset.bopDisabled === '1'; delete el.dataset.bopDisabled; }
    });
    var status = document.getElementById('bop-status');
    if (status && message) status.textContent = message;
    else if (status && !value && B.data) status.textContent = B.data.cars.length + ' installed cars loaded.';
  }
  function run(promise, message) {
    setBusy(true, message);
    return promise.catch(fail).finally(function () { setBusy(false); });
  }
  function modal(title) {
    var dlg = h('dialog', {class: 'bop-dialog'}, h('h2', null, title));
    document.body.appendChild(dlg);
    dlg.addEventListener('close', function () { dlg.remove(); });
    return dlg;
  }
  function actions(dlg, items) {
    dlg.appendChild(h('div', {class: 'actions'}, h('button', {class: 'btn ghost', onclick: function () { dlg.close(); }}, 'Cancel'), items));
    dlg.showModal();
  }
  function note(text, type) { return h('p', {class: 'bop-note' + (type ? ' bop-' + type : '')}, text); }
  function setData(data, fresh) {
    B.data = data;
    if (here() && !B.busy) {
      var status=document.getElementById('bop-status');
      if(status) status.textContent=data.cars.length+' installed cars loaded.';
    }
    if (fresh) {
      B.detail = {}; B.proposal = null; B.evaluated = {}; B.evalErrors = {};
      Object.keys(B.drafts).forEach(function (id) {
        var c = data.cars.find(function (x) { return x.id === id; });
        if (!c || c.fingerprint !== B.drafts[id].fingerprint) delete B.drafts[id];
      });
    }
    if (!data.cars.some(function (c) { return c.id === B.selected; })) B.selected = data.cars.length ? data.cars[0].id : '';
    if (!B.target && car()) B.target = car().class;
    if (!B.custom && !data.classes.some(function (c) { return c.id === B.target; }) && data.classes.length) B.target = data.classes[0].id;
    setTargetMetadata();
  }
  function setTargetMetadata() {
    var target = B.data && B.data.classes.find(function (c) { return c.id === B.target; });
    if (!B.custom && target) { B.group = target.group; B.grid = target.grid; }
  }
  function loadSelection() {
    if (!B.selected) { render(); return Promise.resolve(); }
    var generation = ++B.generation, id = B.selected;
    var p = B.detail[id] ? Promise.resolve(B.detail[id]) : api('/api/bop/car?car=' + encodeURIComponent(id));
    var info = converting ? api('/api/bop/conversion/info?car=' + encodeURIComponent(id) + '&class=' + encodeURIComponent(B.target)) : Promise.resolve(null);
    return Promise.all([p, api('/api/bop/comparison?class=' + encodeURIComponent(B.target) + '&exclude=' + encodeURIComponent(id)), info,
      converting ? api('/api/bop/donor/info?car=' + encodeURIComponent(id)) : Promise.resolve(null)])
      .then(function (results) {
        B.detail[id] = results[0];
        if (generation !== B.generation) return;
        B.comparison = results[1];
        if (converting) {
          B.conversionInfo = results[2];
          if (!B.reference || !B.conversionInfo.references.some(function(c) {return c.id === B.reference;})) B.reference = B.conversionInfo.recommended;
          if (B.inertiaMass == null) B.inertiaMass = B.conversionInfo.baseline.mass;
          B.donorInfo = results[3];
          var staged = B.drafts[id], active = staged && staged.donor_baseline || B.donorInfo.active;
          var saved = B.donorInfo.baselines.find(function(b) {return active && b.id === active.id;}) || B.donorInfo.baselines[0];
          B.donorBaseline = saved ? saved.id : '';
          B.donorOffsets = Object.assign({power:0,aero:0,braking:0,cornering:0}, active && saved && active.id === saved.id ? active.offsets : {});
          if (staged) B.conversionMode = staged.donor_baseline ? 'donor' : 'packages';
          if (!B.donor || !B.donorInfo.donors.some(function(c) {return c.id === B.donor && c.available;})) {
            var recommended = B.donorInfo.donors.find(function(c) {return c.id === B.reference && c.available;}) || B.donorInfo.donors.find(function(c) {return c.available && c.class === B.target;}) || B.donorInfo.donors.find(function(c) {return c.available;});
            B.donor = recommended ? recommended.id : ''; B.donorSources = {};
          }
        }
        render();
        if (B.drafts[id]) updateMetrics(id, 0);
      });
  }
  function select(id) {
    if (B.busy) return;
    B.selected = id; B.carSetup = ''; B.proposal = null; B.inertiaMass = null; B.reference = ''; B.conversionInfo = null; B.donorInfo = null; B.donor = ''; B.donorSources = {};
    renderRail();
    return run(loadSelection(), 'Loading car parameters…');
  }
  function rail() {
    var search = h('input', {type: 'search', placeholder: 'Search cars', 'aria-label': 'Search cars', value: B.search,
      oninput: function () { B.search = search.value; renderCars(); }});
    var filter = h('select', {'aria-label': 'Filter cars by class', onchange: function () { B.filter = filter.value; renderCars(); }},
      h('option', {value: ''}, 'All classes'), B.data.classes.map(function (c) { return h('option', {value: c.id, selected: c.id === B.filter}, c.name + ' · ' + c.count); }));
    var section = h('aside', {class: 'bop-rail'}, h('div', {class: 'bop-rail-top'}, h('h2', null, 'Installed cars'), search, filter),
      h('div', {id: 'bop-cars', class: 'bop-car-list'}));
    return section;
  }
  function renderRail() { renderCars(); footer(); }
  function renderCars() {
    var list = document.getElementById('bop-cars'); if (!list || !B.data) return;
    var q = B.search.toLowerCase(), visible = B.data.cars.filter(function (c) {
      return (!B.filter || B.filter === c.class) && (c.name + ' ' + c.id).toLowerCase().indexOf(q) >= 0;
    });
    fill(list, visible.map(function (c) {
      var staged = B.drafts[c.id] && (Object.keys(B.drafts[c.id].parameters).length || B.drafts[c.id].target_class != null || B.drafts[c.id].tyres != null || B.drafts[c.id].donor_baseline);
      return h('button', {class: 'bop-car' + (c.id === B.selected ? ' selected' : ''), 'aria-pressed': c.id === B.selected, onclick: function () { select(c.id); }},
        h('span', {class: 'bop-car-name'}, c.name, staged ? h('span', {class: 'bop-dot', title: 'Draft changes'}, '●') : null),
        h('span', {class: 'bop-car-class'}, c.class.replace(/_/g, ' ')),
        h('span', {class: 'bop-car-spec'}, f(c.metrics.mass, 'mass') + ' kg · ' + f(c.metrics.power_hp, 'power_hp') + ' hp proxy'),
        h('span', {class: 'bop-car-coverage'}, c.editable_parameters + ' editable values' + (!c.class_editable ? ' · class read-only' : '')));
    }), visible.length ? null : note('No cars match this filter.'));
  }
  function targetControls() {
    var options = B.data.classes.map(function (c) { return h('option', {value: c.id, selected: !B.custom && c.id === B.target}, c.name + ' (' + c.count + ')'); });
    var selectEl = h('select', {'aria-label': converting ? 'Target class' : 'Comparison class', onchange: function () {
      B.custom = selectEl.value === '__new__';
      if (!B.custom) { B.target = selectEl.value; setTargetMetadata(); }
      else { B.target = ''; B.group = car().group; B.grid = car().grid; }
      B.proposal = null; B.reference = '';
      run(loadSelection(), 'Comparing target class…');
    }}, options, converting ? h('option', {value: '__new__', selected: B.custom}, 'Create a class…') : null);
    var controls = h('div', {class: 'bop-target'}, h('label', null, converting ? 'Target class' : 'Comparison class', selectEl));
    if (converting && B.custom) {
      var cls = h('input', {value: B.target, placeholder: 'e.g. League_GT3', 'aria-label': 'New class identifier', onchange: function () {
        B.target = cls.value.trim(); run(loadSelection(), 'Updating comparison…');
      }});
      var group = h('input', {value: B.group, 'aria-label': 'Vehicle group', onchange: function () { B.group = group.value.trim(); }});
      var grid = h('input', {type: 'number', min: 0, max: 1000, step: 1, value: B.grid, 'aria-label': 'Grid grouping', onchange: function () { B.grid = grid.value; }});
      controls.appendChild(h('div', {class: 'bop-custom-grid'}, h('label', null, 'Class identifier', cls), h('label', null, 'Vehicle group', group), h('label', null, 'Grid grouping', grid)));
    } else {
      var selected = B.data.classes.find(function (c) { return c.id === B.target; });
      controls.appendChild(converting ? note(B.group + ' · grid ' + B.grid + (selected && selected.variants > 1 ? ' · class contains different groupings; the most common is used' : '')) :
        h('a', {href:'#/conversion', class:'bop-conversion-link'}, 'Open Car Conversion to change class or upgrade a car'));
    }
    return controls;
  }
  function infoCards() {
    var d = detail(), request = B.drafts[B.selected], evaluated = B.evaluated[B.selected];
    var afterValues = evaluated && evaluated.key === JSON.stringify(request) ? evaluated.after : null;
    return h('div', {id: 'bop-stats', class: 'bop-stats'}, (converting ? ['mass', 'power_hp', 'wing_lift', 'yaw_inertia'] : ['mass', 'power_hp', 'power_to_weight', 'wing_lift']).map(function (id) {
      var m = metric(id), baseline = d.metrics[id], after = afterValues ? afterValues[id] : null;
      var reference = B.comparison && (/^(power_hp|power_to_weight)$/.test(id) ? B.comparison.power_target.summary[id] : B.comparison.reference_summary[id]);
      var saved = converting && B.conversionMode === 'donor' && B.donorInfo && B.donorInfo.baselines.find(function(b) {return b.id === B.donorBaseline;});
      return h('div', {class: 'bop-stat'}, h('span', {class: 'bop-stat-label', title: m.note}, m.name),
        h('strong', null, f(baseline, id), h('small', null, baseline != null ? ' ' + unit(id) : '')),
        after != null && Math.abs(after - baseline) > 1e-5 ? h('span', {class: 'bop-stat-draft'}, 'Draft ' + f(after, id) + ' ' + unit(id)) : null,
        h('span', {class: 'bop-stat-ref'}, converting && B.conversionMode === 'donor' && B.panel !== 'percent' ? saved ? 'Donor baseline ' + f(saved.metrics[id], id) + ' ' + unit(id) : 'Capture a donor baseline' : reference && reference.count ? 'Automatic reference median ' + f(reference.median, id) + ' ' + unit(id) : 'No automatic reference'));
    }));
  }
  function comparePanel() {
    var comparison = B.comparison, candidate = car();
    var cols = B.columns.map(metric).filter(Boolean);
    var members = comparison ? comparison.cars.slice() : [];
    var body = h('div', null, h('div', {class: 'bop-section-head'}, h('div', null, h('h3', null, 'Class comparison'),
      note(members.length + ' other cars in ' + (B.target || 'the target class').replace(/_/g, ' ') + '. Missing data stays unavailable.'))),
      h('details', {class: 'bop-metric-picker'}, h('summary', null, 'Choose comparison metrics'),
        h('div', {class: 'bop-metric-options'}, B.data.metrics.map(function (m) {
          var input = h('input', {type: 'checkbox', checked: B.columns.indexOf(m.id) >= 0, onchange: function () {
            B.columns = input.checked ? B.columns.concat(m.id) : B.columns.filter(function (id) { return id !== m.id; }); renderPanel();
          }});
          return h('label', {title: m.note}, input, m.name);
        }))));
    var tbody = h('tbody', null,
      comparison ? h('tr', {class: 'fieldrow'}, h('td', null, h('b', null, 'Class median'), h('small', null, 'Excludes selected car')),
        cols.map(function (m) { var s = comparison.summary[m.id]; return h('td', {class: 'num', title: s.count + ' decoded references'}, f(s.median, m.id)); })) : null,
      h('tr', {class: 'bop-candidate'}, h('td', null, h('b', null, candidate.name), h('small', null, 'Selected · ' + candidate.class.replace(/_/g, ' '))),
        cols.map(function (m) { return h('td', {class: 'num'}, f(candidate.metrics[m.id], m.id)); })),
      members.map(function (c) {
        return h('tr', null, h('td', null, h('button', {class: 'bop-table-car', onclick: function () { select(c.id); }}, c.name)),
          cols.map(function (m) { return h('td', {class: 'num'}, f(c.metrics[m.id], m.id)); }));
      }));
    body.appendChild(h('div', {class: 'bop-scroll'}, h('table', {class: 'nosort'}, h('thead', null,
      h('tr', null, h('th', null, 'Car'), cols.map(function (m) { return h('th', {class: 'num', title: m.note}, m.name, h('small', null, unit(m.id))); }))), tbody)));
    body.appendChild(powerReferences());
    body.appendChild(note('Power and wing lift are file proxies. Boost, restrictors, tyre grip, diffuser effects and setup changes are not simulated. Use recorded tests to judge pace.'));
    body.appendChild(h('details', {class: 'bop-explanations'}, h('summary', null, 'How these values are calculated'),
      B.data.metrics.map(function (m) { return h('p', null, h('b', null, m.name + ': '), m.note); })));
    return body;
  }
  function powerReferences() {
    if (converting && B.performanceTarget === 'reference' && B.conversionInfo) {
      var donor = B.conversionInfo.references.find(function(c) {return c.id === B.reference;});
      return h('details', {class:'bop-explanations'}, h('summary', null, 'Automatic power reference · ' + (donor ? donor.name : 'choose a car')),
        note(donor && donor.power_target_reason ? 'Power matching will be skipped: ' + donor.power_target_reason :
          donor ? 'Target ' + f(donor.metrics.power_to_weight, 'power_to_weight') + ' kW/t from this car’s engine curve. Restrictors and engine modifiers remain unmodelled; validate on track.' : 'Choose a reference car.'));
    }
    var target = B.comparison && B.comparison.power_target;
    if (!target) return null;
    var ratio = target.summary.power_to_weight;
    return h('details', {class:'bop-explanations'},
      h('summary', null, 'Automatic power reference · ' + target.used.length + ' eligible cars' +
        (ratio.median == null ? ' · unavailable' : ' · ' + f(ratio.median, 'power_to_weight') + ' kW/t')),
      note(target.note),
      target.used.length ? note('Used: ' + target.used.map(function(c) {return c.name;}).join(', ') + '.') : note('No eligible power references. Power matching will be skipped.'),
      target.excluded.length ? h('ul', null, target.excluded.map(function(c) {return h('li', null, c.name + ': ' + c.reason);})) : null);
  }
  function handlingComparison(info) {
    var reference = info.references.find(function(c) {return c.id === B.reference;});
    var own = detail().metrics;
    var ids = ['front_arb_proxy','rear_arb_proxy','front_ride_height','rear_ride_height',
      'front_rebound_travel','rear_rebound_travel','front_bump_travel','rear_bump_travel',
      'front_bumpstop_spring','rear_bumpstop_spring','front_bumpstop_rising','rear_bumpstop_rising'];
    return h('details', {class:'bop-explanations'}, h('summary', null, 'Handling defaults and retained hardware'),
      info.retained.map(function(n) {return note(n);}),
      h('div', {class:'bop-scroll'}, h('table', {class:'nosort'},
        h('thead', null, h('tr', null, h('th', null, 'Metric'), h('th', null, 'Installed car'), h('th', null, reference ? reference.name : 'Reference car'))),
        h('tbody', null, ids.map(function(id) {var m=metric(id);return h('tr', null,
          h('td', {title:m.note}, m.name), h('td', null, f(own[id],id)+' '+unit(id)),
          h('td', null, f(reference ? reference.metrics[id] : null,id)+' '+unit(id)));})))),
      note('These are file defaults, not your saved garage setup. Travel coordinates are not available droop measured from the current ride height. Unknown fields remain unavailable.'));
  }
  function moveOnly() {
    var d = draft();
    d.target_class = B.target; d.group = B.group; d.grid = B.grid;
    persist(); render(); toast('Class change staged. Review before applying.');
  }
  function conversionPanel() {
    var mode = h('select', {'aria-label':'Conversion mode', onchange:function() {B.conversionMode=mode.value; B.proposal=null; renderPanel(); renderStats();}},
      h('option', {value:'donor',selected:B.conversionMode==='donor'}, 'Complete donor baseline'),
      h('option', {value:'packages',selected:B.conversionMode==='packages'}, 'Selected upgrade packages (advanced)'));
    return h('div', null, h('label', null, 'Starting point', mode), B.conversionMode === 'donor' ? donorPanel() : packagePanel());
  }
  function donorPanel() {
    var info = B.donorInfo;
    if (!info) return note('Loading donor baselines…');
    var saved = info.baselines.find(function(b) {return b.id === B.donorBaseline;});
    function stage() {
      if (!saved || info.reason) return;
      var request = {car:B.selected,fingerprint:car().fingerprint,parameters:{},donor_baseline:{id:saved.id,offsets:Object.assign({},B.donorOffsets)}};
      if (B.moveClass) {request.target_class=B.target;request.group=B.group;request.grid=B.grid;}
      B.drafts[B.selected]=request;B.proposal=null;delete B.evalErrors[B.selected];persist();renderRail();updateMetrics(B.selected,0);
    }
    var donor = h('select', {'aria-label':'Complete physics donor',onchange:function() {B.donor=donor.value;B.donorSources={};renderPanel();}},
      h('option', {value:''}, 'Choose a donor'),info.donors.slice().sort(function(a,b) {return (a.class===B.target?0:1)-(b.class===B.target?0:1)||a.name.localeCompare(b.name);}).map(function(c) {
        return h('option', {value:c.id,selected:c.id===B.donor,title:c.reason}, c.name+' · '+c.class.replace(/_/g,' ')+(c.available?c.requires_selection?' · choose file version':'':' · unavailable'));
      }));
    var baseline = h('select', {'aria-label':'Saved donor baseline',onchange:function() {
      B.donorBaseline=baseline.value;
      var active=info.active;B.donorOffsets=Object.assign({power:0,aero:0,braking:0,cornering:0},active && active.id===baseline.value?active.offsets:{});
      renderPanel();renderStats();
    }},h('option',{value:''},'Capture a baseline first'),info.baselines.map(function(b) {return h('option',{value:b.id,selected:b.id===B.donorBaseline},b.donor_name+' · '+fmtDate(b.created));}));
    var move=h('input',{type:'checkbox',checked:B.moveClass,onchange:function() {B.moveClass=move.checked;if(B.drafts[B.selected] && B.drafts[B.selected].donor_baseline)stage();renderPanel();}});
    var selected=info.donors.find(function(c) {return c.id===B.donor;});
    var ready=selected && selected.available && (selected.components || []).every(function(c) {
      return c.versions.length===1 || c.versions.some(function(v) {return v.id===B.donorSources[c.role];});
    });
    var sourcePanel=h('div',{'data-donor-sources':true});
    if(selected) {
      (selected.source_notes || []).forEach(function(n) {sourcePanel.appendChild(note(n));});
      (selected.components || []).forEach(function(c) {
        if(c.versions.length>1) {
          var version=h('select',{'aria-label':'Donor '+c.role.toUpperCase()+' version',onchange:function() {B.donorSources[c.role]=version.value;renderPanel();}},
            h('option',{value:''},'Choose a version to copy'),c.versions.map(function(v) {
              var sources=Array.from(new Set(v.sources.map(function(s) {return s.packed?'Archive '+s.path.split(/[\\/]/).pop():'Loose file';}))).join(', ');
              var mass=c.role==='cdf' && v.metrics.mass!=null?' · '+f(v.metrics.mass,'mass')+' kg':'';
              return h('option',{value:v.id,selected:B.donorSources[c.role]===v.id},sources+mass+' · '+v.id.slice(0,12));
            }));
          sourcePanel.appendChild(h('label',null,c.role.toUpperCase()+' version',version));
        }
      });
      var versions=(selected.components || []).map(function(c) {
        var v=c.versions.length===1?c.versions[0]:c.versions.find(function(v) {return v.id===B.donorSources[c.role];});
        return v?{role:c.role,version:v}:null;
      }).filter(Boolean);
      if(versions.length)sourcePanel.appendChild(h('details',{class:'bop-explanations'},h('summary',null,'Donor files to copy'),
        versions.map(function(c) {return h('div',null,h('strong',null,c.role.toUpperCase()+' · '+c.version.id.slice(0,12)),
          c.version.sources.map(function(s) {return note((s.packed?'Archive: ':'Loose file: ')+s.path+' · '+s.canonical);}));})));
    }
    var panel=h('div',null,h('h3',null,'Start from a complete donor'),
      note('Copies the donor chassis, engine, every gearbox option and vehicle geometry in full. The donor suspension, tyres, clutch and turbo links travel with it. Your car keeps its name, body and liveries.'),
      h('label',null,'Installed donor',donor),sourcePanel,h('div',{class:'actions'},h('button',{class:'btn ghost',disabled:!ready || !!info.reason,onclick:function() {
        run(api('/api/bop/donor/capture','POST',{car:B.selected,fingerprint:car().fingerprint,donor:B.donor,donor_fingerprint:selected.fingerprint,sources:Object.assign({},B.donorSources)}).then(function(result) {
          return api('/api/bop/donor/info?car='+encodeURIComponent(B.selected)).then(function(data) {
            B.donorInfo=data;B.donorBaseline=result.baseline.id;B.donorOffsets={power:0,aero:0,braking:0,cornering:0};renderPanel();renderStats();toast('Donor baseline saved. Stage and review to transfer it.');
          });
        }), 'Saving complete donor baseline…');
      }},'Capture donor baseline')),h('label',null,'Saved baseline',baseline),
      h('label',{class:'conversion-check'},move,'Move car to '+(B.target||'the target class').replace(/_/g,' ')));
    if(info.reason)panel.appendChild(note(info.reason,'warning'));
    if(selected && selected.reason)panel.appendChild(note(selected.reason,'warning'));
    if(saved) {
      panel.appendChild(note('Baseline: '+saved.donor_name+'. 0% restores its physics. Every adjustment recalculates from this saved version, including after an apply or restart.'));
      saved.controls.forEach(function(c) {
        var label=h('strong',null,Number(B.donorOffsets[c.id]||0).toFixed(1)+'%');
        var range=h('input',{type:'range',min:c.min,max:c.max,step:c.step,value:B.donorOffsets[c.id]||0,disabled:!c.available || !!info.reason,'aria-label':'Donor '+c.name,oninput:function() {
          B.donorOffsets[c.id]=Number(range.value);label.textContent=Number(range.value).toFixed(1)+'%';stage();
        }});
        panel.appendChild(h('div',{class:'bop-strength'},h('label',null,c.name,label,range),note(c.note),c.available?null:note(c.reason,'warning')));
      });
      panel.appendChild(h('div',{class:'actions'},h('button',{class:'btn',disabled:!!info.reason || B.moveClass && (!detail().class_editable || !B.target),onclick:function() {stage();toast('Complete donor transfer staged. Review changes before applying.');}},'Stage donor and tuning'),
        h('button',{class:'btn ghost',disabled:!!info.reason,onclick:function() {B.donorOffsets={power:0,aero:0,braking:0,cornering:0};stage();renderPanel();}},'Reset tuning to donor (0%)')));
      panel.appendChild(note('These percentages change physics values, not promised lap time or corner speed. Full geometry can move wheels or collision behaviour relative to your retained body. Reset garage setup defaults and test zero offsets first.'));
      panel.appendChild(note('Pinned installed components: '+(saved.pinned_components.join(', ').toUpperCase()||'none')+'.'));
      saved.notes.forEach(function(n) {panel.appendChild(note(n,'warning'));});
    }
    return panel;
  }
  function packagePanel() {
    var d = detail(), info = B.conversionInfo;
    if (!info) return note('Loading conversion references…');
    function invalidate() {B.proposal=null;var old=document.querySelector('#bop-panel .bop-proposal');if(old)old.remove();}
    var reference = h('select', {'aria-label':'Conversion reference car', onchange:function() {B.reference=reference.value; B.proposal=null; renderPanel();}},
      h('option', {value:''}, 'Choose a reference car'),
      info.references.slice().sort(function(a,b) {return (a.class === B.target ? 0 : 1) - (b.class === B.target ? 0 : 1) || a.name.localeCompare(b.name);}).map(function(c) {
        return h('option', {value:c.id, selected:c.id===B.reference}, c.name + ' · ' + c.class.replace(/_/g,' '));
      }));
    var performance = h('select', {'aria-label':'Conversion performance target', onchange:function() {B.performanceTarget=performance.value; B.proposal=null; renderPanel();}},
      h('option', {value:'class', selected:B.performanceTarget==='class'}, 'Target class median'),
      h('option', {value:'reference', selected:B.performanceTarget==='reference'}, 'Reference car'));
    var move = h('input', {type:'checkbox', checked:B.moveClass, onchange:function() {B.moveClass=move.checked; B.proposal=null; renderPanel();}});
    var label = h('strong', null, B.strength + '% toward performance target');
    var range = h('input', {type:'range', min:0, max:100, step:5, value:B.strength, 'aria-label':'Conversion performance matching', oninput:function() {
      B.strength=Number(range.value); label.textContent=B.strength+'% toward performance target'; invalidate();
    }});
    var inertia = h('input', {type:'number', min:100, max:10000, step:'any', value:B.inertiaMass == null ? '' : B.inertiaMass,
      'aria-label':'Original mass for inertia scaling', onchange:function() {B.inertiaMass=Number(inertia.value); invalidate();}});
    var panel = h('div', null, h('h3', null, 'Build a class conversion'),
      note('Choose the packages to upgrade. Each car keeps its engine curve, gearing, centre of gravity and geometry. You can edit every supported draft value before applying.'),
      h('label', {class:'conversion-check'}, move, 'Move car to ' + (B.target || 'the target class').replace(/_/g,' ')),
      h('div', {class:'conversion-reference-grid'}, h('label', null, 'Reference car for upgrade packages', reference), h('label', null, 'Mass and power target', performance)),
      h('div', {class:'bop-strength'}, h('label', null, 'Performance matching', label, range),
        note('This slider adjusts mass and power only. Selected tyre and aero packages use the reference model in full.')),
      h('div', {class:'bop-axis-grid'}, info.modules.map(function(m) {
        var input = h('input', {type:'checkbox', checked:!!B.modules[m.id], onchange:function() {B.modules[m.id]=input.checked; invalidate();}});
        return h('label', null, input, h('span', null, h('b', null, m.name), h('small', null, m.description)));
      })), powerReferences(), handlingComparison(info), h('details', {class:'conversion-baseline'}, h('summary', null, 'Inertia baseline · ' + info.baseline.source),
        h('label', null, 'Original mass for inertia scaling (kg)', inertia),
        note('Use the mass belonging to the original inertia values. Apply history supplies the baseline when available. Scaling assumes the mass distribution stays proportional.')),
      h('div', {class:'actions'}, h('button', {class:'btn', disabled:!B.target || (B.moveClass && !d.class_editable), onclick:function() {
        run(api('/api/bop/conversion/propose','POST',{car:B.selected,target_class:B.target,group:B.group,grid:B.grid,
          reference:B.reference,performance_target:B.performanceTarget,strength:B.strength/100,move_class:B.moveClass,
          inertia_mass:B.inertiaMass,modules:Object.keys(B.modules).filter(function(k) {return B.modules[k];})}).then(function(p) {
            B.proposal=p; B.drafts[B.selected]=p.edit; B.evaluated[B.selected]={key:JSON.stringify(p.edit),after:p.after};
            delete B.evalErrors[B.selected]; persist(); render(); toast('Conversion draft staged. Check package coverage and review the changes.');
          }), 'Building conversion package…');
      }}, 'Build conversion draft'), h('button', {class:'btn ghost',disabled:!d.class_editable || !B.target,onclick:moveOnly}, 'Stage class change only')));
    if (d.power_target_reason) panel.appendChild(note('Automatic power matching is unavailable for this car: ' + d.power_target_reason, 'warning'));
    if (!d.class_editable) panel.appendChild(note('Class definitions are read-only. Turn off class reassignment to build a physics-only draft; Source details show the reason.', 'warning'));
    if (B.custom && B.performanceTarget==='class') panel.appendChild(note('A new class has no median yet. Choose Reference car for its mass and power target.'));
    if (B.proposal && B.proposal.modules) {
      var p=B.proposal, skipped=p.modules.filter(function(m) {return m.status==='skipped';});
      panel.appendChild(h('div',{class:'bop-proposal'},h('h3',null,'Conversion coverage'),
        note((p.reference ? 'Reference: '+p.reference+'. ' : '') + p.changes.length+' parameter and class changes staged.'),
        skipped.length ? note(skipped.length+' selected package'+(skipped.length===1?' was':'s were')+' skipped. These packages will not change; see the reasons below.','warning') : null,
        h('div',{class:'conversion-coverage'},p.modules.map(function(m) {return h('div',{class:'conversion-coverage-row'},
          h('span',{class:'conversion-status '+m.status},m.status==='ready'?'Ready':m.status==='unchanged'?'Already matches':'Skipped'),
          h('div',null,h('b',null,m.name),note(m.message)));})),
        h('details',null,h('summary',null,'Exact proposed changes · '+p.changes.length),
          h('div',{class:'bop-scroll'},h('table',{class:'nosort'},h('thead',null,h('tr',null,h('th',null,'Parameter'),h('th',null,'Installed'),h('th',null,'Draft'))),
            h('tbody',null,p.changes.map(function(c) {function display(v) {return typeof v==='number'?Number(v.toPrecision(7)):String(v);}
              return h('tr',null,h('td',null,c.parameter),h('td',null,display(c.before)),h('td',null,display(c.after)+' '+c.unit));}))))),
        p.notes.map(function(n) {return note(n);})));
    }
    return panel;
  }
  function proposalPanel() {
    var d = detail();
    var range = h('input', {type: 'range', min: 0, max: 100, step: 5, value: B.strength, 'aria-label': 'Adjustment strength', oninput: function () {
      B.strength = Number(range.value); label.textContent = B.strength + '% toward class median';
    }});
    var label = h('strong', null, B.strength + '% toward class median');
    var axes = [['mass', 'Mass', 'Move toward class mass, keeping part of the weight difference.'],
      ['power_to_weight', 'Power per tonne', 'Scale the existing engine through its chassis multiplier.'],
      ['body_drag', 'Body base drag', 'Adjust the base coefficient; this does not match total drag.'],
      ['wing_lift', 'Wing lift proxy', 'Scale both wing polynomials together, retaining their balance.'],
      ['brakes', 'Brake torque', 'Scale decoded corner brake torques while keeping their ratio.']];
    var panel = h('div', null, h('h3', null, 'BOP adjustment draft'),
      note('Move selected performance values toward the comparison class. Class reassignment and conversion packages are on Car Conversion.'),
      powerReferences(),
      h('div', {class: 'bop-strength'}, h('label', null, 'Adjustment strength', label, range), h('div', null, 'Keep installed values', ' → ', 'Reach class median')),
      h('div', {class: 'bop-axis-grid'}, axes.map(function (axis) {
        var input = h('input', {type: 'checkbox', checked: B.axes[axis[0]], onchange: function () { B.axes[axis[0]] = input.checked; }});
        return h('label', null, input, h('span', null, h('b', null, axis[1]), h('small', null, axis[2])));
      })),
      h('div', {class: 'actions'}, h('button', {class: 'btn', disabled: !B.comparison || !B.comparison.cars.length,
        onclick: function () {
          run(api('/api/bop/propose', 'POST', {car: B.selected, target_class: B.target, group: B.group, grid: B.grid,
            reassign_class: false, strength: B.strength / 100, axes: Object.keys(B.axes).filter(function (key) { return B.axes[key]; })}).then(function (proposal) {
              B.proposal = proposal; B.drafts[B.selected] = proposal.edit;
              B.evaluated[B.selected] = {key: JSON.stringify(proposal.edit), after: proposal.after}; delete B.evalErrors[B.selected];
              persist(); render(); toast('Proposal staged. You can now fine-tune it manually.');
            }), 'Building proportional proposal…');
        }}, 'Build proposal')));
    if (B.proposal && B.proposal.edit.car === B.selected) {
      var p = B.proposal;
      panel.appendChild(h('div', {class: 'bop-proposal'}, h('h3', null, 'Proposed changes'),
        h('table', {class: 'nosort'}, h('thead', null, h('tr', null, h('th', null, 'Metric'), h('th', {class: 'num'}, 'Installed'), h('th', {class: 'num'}, 'Proposed'))),
          h('tbody', null, B.data.metrics.filter(function (m) { return p.before[m.id] != null && p.after[m.id] != null && Math.abs(p.before[m.id] - p.after[m.id]) > 1e-5; }).map(function (m) {
            return h('tr', null, h('td', null, m.name), h('td', {class: 'num'}, f(p.before[m.id], m.id) + ' ' + unit(m.id)), h('td', {class: 'num'}, f(p.after[m.id], m.id) + ' ' + unit(m.id)));
          }))), h('ul', null, p.reasons.map(function (r) { return h('li', null, r); })), p.notes.map(function (n) { return note(n); })));
    }
    return panel;
  }
  function numberInput(p) {
    var stored = B.drafts[B.selected], current = stored && stored.parameters[p.id] != null ? stored.parameters[p.id] : p.value;
    var input = h('input', {type: 'number', step: p.integer ? '1' : 'any', min: p.minimum, max: p.maximum,
      value: Number(Number(current).toPrecision(9)), disabled: !p.editable, 'aria-label': p.label,
      title: p.reason || p.note || p.label, oninput: function () {
        if (!input.checkValidity() || !input.value.trim() || !isFinite(Number(input.value))) {
          input.classList.add('bop-invalid'); input.setAttribute('aria-invalid', 'true'); footer(); return;
        }
        input.classList.remove('bop-invalid'); input.removeAttribute('aria-invalid');
        var value = Number(input.value), edit = draft();
        forgetPercentage(edit, p.id);
        if (Math.abs(value - p.value) <= Math.max(1e-9, Math.abs(p.value) * 1e-8)) delete edit.parameters[p.id];
        else edit.parameters[p.id] = value;
        B.proposal = null; delete B.evalErrors[B.selected]; persist(); renderRail(); renderStats(); drawCurves(); updateMetrics(B.selected);
      }});
    return input;
  }
  function forgetPercentage(edit, parameter) {
    var state = edit.percentage_tuning;
    if (!state || !state.categories) return;
    Object.keys(state.categories).forEach(function (id) {
      var entry = state.categories[id];
      if (!entry || !entry.base || Object.prototype.hasOwnProperty.call(entry.base, parameter) ||
          id === 'bars' && parameter === 'cdf.spring_based_arb.0.0') delete state.categories[id];
    });
    if (!Object.keys(state.categories).length) delete edit.percentage_tuning;
  }
  function percentagePanel() {
    var request = B.drafts[B.selected];
    if (request && request.donor_baseline) return h('div', null, h('h3', null, 'Percentage tuning'),
      note('Apply or reset the staged complete donor before adjusting installed values.'));
    var categories = detail().percentage_categories || [];
    var states = request && request.percentage_tuning && request.percentage_tuning.categories || {};
    function stage(category, percent) {
      var id = B.selected, edit = draft(), snapshot = JSON.stringify(edit);
      run(api('/api/bop/tune', 'POST', {edit: JSON.parse(snapshot), category: category.id, percent: percent}).then(function (result) {
        if (JSON.stringify(B.drafts[id]) !== snapshot) return;
        B.drafts[id] = result.edit;
        B.evaluated[id] = {key: JSON.stringify(result.edit), after: result.after};
        delete B.evalErrors[id]; B.proposal = null; persist(); render();
      }), 'Staging ' + category.name.toLowerCase() + ' change…');
    }
    var panel = h('div', null, h('h3', null, 'Percentage tuning'),
      note('Adjust a category in 0.25% steps, then Review changes. Positive increases its values; negative decreases them.'),
      note('Each category starts from its current draft values. +2% replaces +1%; it does not compound. Reset to 0% restores that start. After applying, the installed values become the new start.'));
    panel.appendChild(h('div', {class: 'bop-percentage-grid'}, categories.map(function (category) {
      if (category.id === 'bars' && request && request.parameters && request.parameters['cdf.spring_based_arb.0.0'] != null && request.parameters['cdf.spring_based_arb.0.0'] !== 1)
        category = Object.assign({}, category, {available:false, reason:'Percentage bar-rate scaling requires spring-based anti-roll bars.'});
      var state = states[category.id], percent = state && typeof state.percent === 'number' && isFinite(state.percent) ? state.percent : 0;
      function commit() {
        if (B.busy || !input.value.trim() || !input.checkValidity() || !isFinite(Number(input.value))) return;
        var value = Number(input.value);
        if (value !== percent) stage(category, value);
      }
      var input = h('input', {type: 'number', step: category.step, min: category.minimum, max: category.maximum,
        value: percent.toFixed(2), disabled: !category.available, 'aria-label': category.name + ' change (%)',
        oninput: function () {
          var valid = input.value.trim() && input.checkValidity() && isFinite(Number(input.value));
          input.classList.toggle('bop-invalid', !valid);
          if (valid) input.removeAttribute('aria-invalid'); else input.setAttribute('aria-invalid', 'true');
          footer();
        }, onchange: commit, onblur: commit, onkeydown: function (event) {
          if (event.key === 'Enter') { event.preventDefault(); commit(); }
        }});
      function tick(delta) {
        // Step from the committed percentage, so blur/change cannot apply twice.
        stage(category, Number((percent + delta).toFixed(2)));
      }
      return h('section', {class: 'bop-percentage-category'}, h('h4', null, category.name),
        note(category.description),
        h('div', {class: 'bop-percentage-control'},
          h('button', {class: 'btn ghost small', disabled: !category.available || percent <= category.minimum,
            'aria-label': 'Decrease ' + category.name + ' by 0.25%', onclick: function () { tick(-category.step); }}, '−0.25'),
          h('label', null, 'Change (%)', input),
          h('button', {class: 'btn ghost small', disabled: !category.available || percent >= category.maximum,
            'aria-label': 'Increase ' + category.name + ' by 0.25%', onclick: function () { tick(category.step); }}, '+0.25')),
        h('button', {class: 'btn ghost small', disabled: !state, onclick: function () { stage(category, 0); },
          'aria-label': 'Reset ' + category.name + ' to 0%'}, 'Reset to 0%'),
        !category.available ? note(category.reason, 'warning') : null);
    })));
    panel.appendChild(note('Mass and brake torque round to their stored whole units. Tyre grip is not decoded; choose tyre-model references in Manual tuning. Individual edits turn that category’s percentage back to 0% and keep its current draft values.'));
    return panel;
  }
  function curves() {
    return h('div', {id: 'bop-curves', class: 'bop-curve-grid'});
  }
  function drawCurves() {
    var container = document.getElementById('bop-curves'), d = detail();
    if (!container || !d) return;
    if (!d.curves.length || !d.curves[0].rows.length) { fill(container, note('No supported engine torque table was found.')); return; }
    var rows = d.curves[0].rows, params = B.drafts[B.selected] ? B.drafts[B.selected].parameters : {};
    var p = d.parameters.find(function (p) { return p.id === 'cdf.power_multiplier.0.0'; });
    var originalMultiplier = p ? p.value : 1, multiplier = params['cdf.power_multiplier.0.0'] == null ? originalMultiplier : params['cdf.power_multiplier.0.0'];
    var points = rows.map(function (r, index) {
      var parameter = d.parameters.find(function (p) { return p.id === r.torque_id; });
      var tq = parameter && params[parameter.id] != null ? params[parameter.id] : r.torque;
      return {rpm: r.rpm, installed: r.torque * originalMultiplier, draft: tq * multiplier};
    }).filter(function (r) { return r.rpm > 0 && (r.installed > 0 || r.draft > 0); });
    fill(container, ['Torque (Nm)', p ? 'Power proxy (hp)' : 'Curve power only (hp)'].map(function (title, graph) {
      var width = 540, height = 185, left = 48, top = 22, bottom = 150, right = 520;
      var maxRpm = Math.max.apply(null, points.map(function (r) { return r.rpm; }));
      function value(r, key) { return graph ? r[key] * r.rpm * Math.PI / 30000 / 0.745699872 : r[key]; }
      var high = Math.max.apply(null, points.map(function (r) { return Math.max(value(r, 'installed'), value(r, 'draft')); })) * 1.08;
      high = Math.max(1, high); maxRpm = Math.max(1, maxRpm);
      var chart = svg('svg', {viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': title + ': installed and draft map 1 curves'});
      [0, 0.5, 1].forEach(function (fraction) {
        var y = bottom - (bottom - top) * fraction;
        chart.appendChild(svg('line', {x1: left, x2: right, y1: y, y2: y, stroke: 'var(--line)'}));
        chart.appendChild(svg('text', {x: left - 8, y: y + 4, 'text-anchor': 'end', fill: 'var(--muted)', 'font-size': 10}, Math.round(high * fraction)));
      });
      [0, 0.5, 1].forEach(function (fraction) {
        chart.appendChild(svg('text', {x: left + (right - left) * fraction, y: 170, 'text-anchor': 'middle', fill: 'var(--muted)', 'font-size': 10}, Math.round(maxRpm * fraction) + ' rpm'));
      });
      ['installed', 'draft'].forEach(function (key) {
        var path = points.map(function (r, index) { return (index ? 'L' : 'M') + (left + (right - left) * r.rpm / maxRpm).toFixed(2) + ',' + (bottom - (bottom - top) * value(r, key) / high).toFixed(2); }).join(' ');
        chart.appendChild(svg('path', {d: path, fill: 'none', stroke: key === 'draft' ? 'var(--accent)' : 'var(--muted)',
          'stroke-width': key === 'draft' ? 2.5 : 2, 'stroke-dasharray': key === 'installed' ? '5 4' : null}));
      });
      return h('div', {class: 'bop-curve'}, h('h4', null, title), chart, h('small', null, 'Positive map 1 · dashed installed · solid draft · includes over-rev rows'));
    }));
  }
  function manualPanel() {
    if (B.drafts[B.selected] && B.drafts[B.selected].donor_baseline) return h('div',null,h('h3',null,'Donor tuning is staged'),
      note('Use the donor sliders to tune the saved baseline. Apply this transfer before making manual edits to its installed values.'),
      h('button',{class:'btn ghost',onclick:function() {B.conversionMode='donor';B.panel='convert';renderPanel();}},'Open donor controls'));
    var d = detail(), groups = {};
    d.parameters.forEach(function (p) { (groups[p.group] || (groups[p.group] = [])).push(p); });
    var scale = h('input', {type: 'number', min: 1, max: 500, step: 'any', value: 100, 'aria-label': 'Torque scale percentage'});
    var model = h('select', {'aria-label': 'Tyre model', disabled: !d.tyres_editable, onchange: function () {
      var request = draft();
      if (model.value === d.tyres) delete request.tyres; else request.tyres = model.value;
      if (request.car_setup) delete request.car_setup.tyre_reference;
      persist(); renderRail(); updateMetrics(B.selected);
    }}, h('option', {value: ''}, d.tyres ? 'Choose a model' : 'No decoded tyre link'), B.data.tyre_models.map(function (t) {
      var request = B.drafts[B.selected]; return h('option', {value: t, selected: t === (request && request.tyres || d.tyres)}, t);
    }));
    var panel = h('div', null, h('h3', null, 'Manual tuning'),
      note('Change a value to stage it. Every car keeps its own draft; Review changes checks the edited files before applying anything.'),
      h('div', {class: 'bop-manual-toolbar'}, h('label', null, 'Installed tyre-model reference', model)),
      note('Tyre references select an existing installed model. Tyre grip curves and compound physics are not decoded here.'), curves());
    if (!d.tyres_editable && d.tyres_reason) panel.appendChild(note('Tyre reference read-only: ' + d.tyres_reason));
    if (d.parameters.some(function (p) { return p.editable && p.id.indexOf('edf.torque.') === 0; })) {
      panel.appendChild(h('div', {class: 'bop-scale'}, h('label', null, 'Positive torque scale (%)', scale), h('button', {class: 'btn ghost small', onclick: function () {
        if (!scale.checkValidity() || !scale.value) return fail(new Error('Enter a torque scale from 1 to 500%.'));
        var factor = Number(scale.value) / 100, request = draft();
        d.parameters.forEach(function (p) {
          if (p.editable && p.id.indexOf('edf.torque.') === 0) {
            var current = request.parameters[p.id] == null ? p.value : request.parameters[p.id];
            if (current > 0) request.parameters[p.id] = current * factor;
          }
        });
        B.proposal = null; persist(); render(); updateMetrics(B.selected, 0);
      }}, 'Scale current draft'), note('Scales positive torque across all decoded maps; negative idle torque and engine braking are preserved.')));
    }
    Object.keys(groups).forEach(function (group) {
      var fields = groups[group];
      var section = h('details', {class: 'bop-parameters', open: group === 'Engine' || group === 'Chassis'},
        h('summary', null, group + ' · ' + fields.length + ' values'),
        h('div', {class: 'bop-scroll'}, h('table', {class: 'nosort'}, h('thead', null, h('tr', null,
          h('th', null, 'Parameter'), h('th', {class: 'num'}, 'Installed'), h('th', null, 'Draft'), h('th', null, 'Unit'))),
          h('tbody', null, fields.map(function (p) {
            return h('tr', null, h('td', {title: p.note || p.reason}, p.label, !p.editable ? h('small', {class: 'bop-readonly'}, 'Read-only: ' + p.reason) : null),
              h('td', {class: 'num'}, Number(p.value.toPrecision(7)).toString()), h('td', null, numberInput(p)), h('td', null, p.unit));
          })))));
      panel.appendChild(section);
    });
    if (!d.parameters.length) panel.appendChild(note('No supported parameters were decoded for this car. Source details below explain which files are missing or unsupported.', 'warning'));
    return panel;
  }
  function measuredPanel() {
    if (B.recordings == null) {
      api('/api/bop/recordings').then(function (data) { B.recordings = data.recordings; if (here() && B.panel === 'measured') renderPanel(); }).catch(fail);
      return note('Loading recorded races…');
    }
    var panel = h('div', null, h('h3', null, 'Recorded performance'),
      note('Compare pace, speed, sectors and corner types from your existing race analysis. Driver skill, fuel, tyres, traffic and conditions can change these results; a file match alone cannot predict them.'));
    if (!B.recordings.length) return h('div', null, panel, note('No completed race recordings are available yet.'),
      h('a', {class: 'btn ghost', href: '#/recordings'}, 'Open recordings'));
    var selectEl = h('select', {'aria-label': 'Recorded race', onchange: function () {
      B.recording = selectEl.value;
      if (!B.recording) { B.measured = null; renderPanel(); return; }
      var id = B.recording;
      run(api('/api/bop/measured?recording=' + encodeURIComponent(id)).then(function (data) {
        if (id === B.recording) { B.measured = data; renderPanel(); }
      }), 'Analysing recorded cars…');
    }}, h('option', {value: ''}, 'Choose a recorded race'), B.recordings.map(function (r) {
      return h('option', {value: r.id, selected: r.id === B.recording}, (r.track || '') + ' ' + (r.layout || '') + ' · ' + (r.label || r.id));
    }));
    panel.appendChild(h('label', {class: 'bop-recording-picker'}, 'Race recording', selectEl));
    if (B.measured) {
      var columns = [['pace', 'Clean-lap pace', 's'], ['best_lap', 'Best lap', 's'], ['top_speed', 'Top speed', 'km/h'],
        ['s1_delta', 'S1 vs field', 's'], ['s2_delta', 'S2 vs field', 's'], ['s3_delta', 'S3 vs field', 's'],
        ['apex_delta_slow', 'Slow corners vs field', 'km/h'], ['apex_delta_medium', 'Medium corners vs field', 'km/h'], ['apex_delta_fast', 'Fast corners vs field', 'km/h']];
      panel.appendChild(h('div', {class: 'bop-scroll'}, h('table', null, h('thead', null, h('tr', null, h('th', null, 'Recorded car'), h('th', {class: 'num'}, 'Drivers'),
        columns.map(function (column) { return h('th', {class: 'num'}, column[1], h('small', null, column[2])); }))),
        h('tbody', null, (B.measured.cars || []).map(function (c) {
          return h('tr', null, h('td', null, c.car), h('td', {class: 'num'}, c.drivers), columns.map(function (column) {
            var value = c[column[0]];
            return h('td', {class: 'num'}, value == null ? 'Unavailable' : (column[0] === 'pace' || column[0] === 'best_lap' ? lapTime(value) : Number(value).toFixed(2)));
          }));
        })))));
      panel.appendChild(h('a', {class: 'btn ghost small', href: '#/cars/' + encodeURIComponent(B.recording)}, 'Open full car analysis'));
    }
    panel.appendChild(note('For a BOP test, use the same driver and repeat fuel, setup, tyre and weather conditions. Check several clean laps on tracks with different demands.'));
    return panel;
  }
  function renderPanel() {
    var content = document.getElementById('bop-panel'); if (!here() || !content || !detail()) return;
    var y = document.getElementById('main').scrollTop;
    fill(content, B.panel === 'convert' ? conversionPanel() : B.panel === 'compare' ? comparePanel() : B.panel === 'homologate' ? proposalPanel() : B.panel === 'percent' ? percentagePanel() : B.panel === 'manual' ? manualPanel() : measuredPanel());
    renderStats();
    document.querySelectorAll('.bop-tabs button').forEach(function (b) { b.classList.toggle('selected', b.dataset.panel === B.panel); b.setAttribute('aria-pressed', b.dataset.panel === B.panel); });
    drawCurves(); document.getElementById('main').scrollTop = y;
  }
  function sourceDetails(d) {
    return h('details', {class: 'bop-sources'}, h('summary', null, 'Source details and data coverage'),
      d.notes.map(function (n) { return note(n); }), Object.keys(d.errors).map(function (role) { return note(role.toUpperCase() + ': ' + d.errors[role].join('; '), 'warning'); }),
      h('ul', null, d.sources.map(function (s) { return h('li', null, h('b', null, s.role.toUpperCase() + ' · ' + s.kind + ': '), s.path,
        s.kind === 'Package' ? h('small', null, s.canonical) : null); })),
      note('Unsupported encodings, shared per-car physics and Oodle-packed entries stay read-only. Full donor copies can grow supported packages; archives with unsupported CRC or section tables need rebuilding.'));
  }
  function workspace() {
    var selected = car(), d = detail();
    if (!selected) return h('section', {class: 'bop-work'}, h('h2', null, 'No selectable car definitions found'),
      note('Scan an installed game folder with its loose mod files and package files. The editor needs each car’s CRD to identify its class and physics model.'));
    if (!d) return h('section', {class: 'bop-work'}, note('Loading car…'));
    var request = B.drafts[B.selected];
    var head = h('div', {class: 'bop-car-head'}, h('div', null, h('p', {class: 'kicker'}, selected.class.replace(/_/g, ' ')),
      h('h2', null, selected.name), h('p', {class: 'bop-note'}, d.editable_parameters + ' editable parameters · ' + d.sources.length + ' source copies')),
      h('button', {class: 'btn ghost small', disabled: !request, onclick: function () {
        delete B.drafts[B.selected]; delete B.evaluated[B.selected]; delete B.evalErrors[B.selected]; B.proposal = null; persist(); render();
      }}, 'Reset this draft'));
    var tabs = h('div', {class: 'bop-tabs', role: 'group', 'aria-label': converting ? 'Car Conversion views' : 'Balance of Performance views'},
      (converting ? [['convert', 'Conversion package'], ['compare', 'Compare class'], ['percent', 'Percentage tuning'], ['manual', 'Manual tuning'], ['measured', 'Recorded tests']] :
        [['compare', 'Compare class'], ['homologate', 'Adjustment draft'], ['percent', 'Percentage tuning'], ['manual', 'Manual tuning'], ['measured', 'Recorded tests']]).map(function (tab) {
        return h('button', {class: tab[0] === B.panel ? 'selected' : '', 'data-panel': tab[0], 'aria-pressed': tab[0] === B.panel,
          onclick: function () { B.panel = tab[0]; renderPanel(); }}, tab[1]);
      }));
    return h('section', {class: 'bop-work'}, head, carSetupControls(), targetControls(), infoCards(), tabs, h('div', {id: 'bop-panel'}), sourceDetails(d));
  }
  function review() {
    var request = edits(); if (!request.length) return;
    run(api('/api/bop/preview', 'POST', {edits: request}).then(function (plan) {
      var dlg = modal(converting ? 'Review Car Conversion' : 'Review Balance of Performance');
      dlg.appendChild(note(plan.changes.length + ' cars · ' + plan.count + ' game files. Close AMS2 and your content manager before applying.'));
      dlg.appendChild(note('Full-file backups: ' + (plan.backup_bytes / 1048576).toFixed(1) + ' MB. Apply also prepares temporary copies before replacing any file.'));
      plan.changes.forEach(function (change) {
        dlg.appendChild(h('h3', null, change.name));
        if (change.car_setup) dlg.appendChild(note('Car setup: ' + change.car_setup.name));
        if (change.percentage_tuning) {
          var labels = (B.detail[change.id] && B.detail[change.id].percentage_categories || []).reduce(function (all, c) { all[c.id] = c.name; return all; }, {});
          dlg.appendChild(note(Object.keys(change.percentage_tuning.categories).map(function (id) {
            var percent = change.percentage_tuning.categories[id].percent;
            return (labels[id] || id) + ': ' + (percent > 0 ? '+' : '') + percent.toFixed(2) + '%';
          }).join(' · ')));
        }
        dlg.appendChild(h('table', {class: 'nosort'}, h('thead', null, h('tr', null, h('th', null, 'Change'), h('th', null, 'Installed'), h('th', null, 'Draft'))),
          h('tbody', null, change.parameters.map(function (p) {
            function display(value) { return typeof value === 'number' ? Number(value.toPrecision(7)).toString() : String(value); }
            return h('tr', null, h('td', null, p.parameter), h('td', null, display(p.before)), h('td', null, display(p.after) + ' ' + p.unit));
          }))));
      });
      dlg.appendChild(h('details', null, h('summary', null, 'Files that will be backed up and changed'), h('ul', null, plan.files.map(function (p) { return h('li', null, p); }))));
      plan.notes.forEach(function (n) { dlg.appendChild(note(n)); });
      var button = h('button', {class: 'btn', disabled: !plan.count, onclick: function () {
        button.disabled = true;
        run(api('/api/bop/apply', 'POST', {token: plan.token}).then(function (result) {
          dlg.close(); B.drafts = {}; persist();
          return api('/api/bop').then(function (data) { setData(data, true); return loadSelection(); }).then(function () {
            toast(result.changed + ' files updated. Backup saved; Undo last apply restores them.');
          });
        }).catch(function (error) { button.disabled = false; throw error; }), 'Applying reviewed changes…');
      }}, 'Apply changes');
      actions(dlg, button);
    }), 'Checking draft and package capacity…');
  }
  function footer() {
    var el = document.getElementById('bop-footer'); if (!here() || !el || !B.data) return;
    var count = edits().length, errors = Object.keys(B.evalErrors).filter(function (id) { return B.drafts[id]; });
    var invalid = !!document.querySelector('.bop-editor .bop-invalid') || errors.length > 0;
    fill(el, h('div', null, h('strong', null, count ? count + (count === 1 ? ' car has' : ' cars have') + ' staged changes' : 'No changes staged'),
      note(errors.length ? B.evalErrors[errors[0]] : invalid ? 'Fix the highlighted value before reviewing.' : 'Drafts do not change the game. Review and apply when ready.')),
      h('div', {class: 'actions'}, h('button', {class: 'btn ghost', disabled: !count || invalid, onclick: saveProfile}, 'Save profile'),
        h('button', {class: 'btn', disabled: !count || invalid, onclick: review}, 'Review changes')));
  }
  function saveProfile() {
    var dlg = modal('Save a league physics profile'), input = h('input', {placeholder: 'e.g. GT3 Gen 0 · Round 1', 'aria-label': 'Profile name', maxlength: 100});
    dlg.appendChild(note('Profiles contain changes and starting-file fingerprints. Donor profiles also need the same baseline captured locally on each machine; game binaries are not exported.'));
    dlg.appendChild(input);
    actions(dlg, h('button', {class: 'btn', onclick: function () {
      run(api('/api/bop/profiles', 'POST', {format: 'ams2season-bop', version: 1, name: input.value, edits: edits()}).then(function (result) {
        B.profile = result.id; dlg.close(); return api('/api/bop');
      }).then(function (data) { B.data.profiles = data.profiles; render(); toast('Physics profile saved.'); }), 'Saving profile…');
    }}, 'Save profile'));
    input.focus();
  }
  function loadProfile(profile) {
    return api('/api/bop/profile/validate', 'POST', profile).then(function (checked) {
      if (!converting && checked.edits.some(classEdit)) {
        handoff(checked.edits); location.hash='#/conversion'; toast('This profile includes class conversion. Opened on Car Conversion.'); return;
      }
      checked.edits.forEach(function (edit) { B.drafts[edit.car] = edit; delete B.evalErrors[edit.car]; });
      B.proposal = null; persist();
      if (converting) {
        var chosen=B.drafts[B.selected];
        if(chosen && chosen.target_class) {B.target=chosen.target_class;B.custom=!B.data.classes.some(function(c) {return c.id===B.target;});B.group=chosen.group;B.grid=chosen.grid;}
        return loadSelection().then(function() {toast('Profile staged. Review changes before applying.');});
      }
      render(); updateMetrics(B.selected, 0); toast('Profile staged. Review changes before applying.');
    });
  }
  function refreshCarSetups() {
    return api('/api/bop/car-setups').then(function (data) { B.data.car_setups = data.setups; });
  }
  function stageCarSetup(result) {
    var edit = result.edit;
    if (!converting && classEdit(edit)) {
      delete B.drafts[edit.car]; delete B.evaluated[edit.car]; delete B.evalErrors[edit.car]; persist();
      conversionHandoffSelection = edit.car; handoff([edit]); location.hash = '#/conversion';
      toast('Car setup staged on Car Conversion. Review changes before applying.'); return;
    }
    B.drafts[edit.car] = edit; delete B.evalErrors[edit.car];
    B.evaluated[edit.car] = {key: JSON.stringify(edit), after: result.after};
    B.proposal = null; persist();
    if (converting) {
      B.target = edit.target_class || car().class;
      B.custom = !B.data.classes.some(function (c) { return c.id === B.target; });
      B.group = edit.group || car().group; B.grid = edit.grid || car().grid;
      return loadSelection().then(function () { toast('Car setup loaded. Review changes before applying.'); });
    }
    render(); toast(Object.keys(edit.parameters).length || edit.tyres || edit.target_class ?
      'Car setup loaded. Review changes before applying.' : 'Car setup loaded. It matches the installed settings.');
  }
  function saveCarSetup() {
    var id = B.selected, pending = false, dlg = modal('Save setup for ' + car().name);
    var input = h('input', {'aria-label': 'Car setup name', maxlength: 100, placeholder: 'e.g. Road America · power trial'});
    dlg.appendChild(note('Saves this car’s supported installed settings plus its staged edits, including class and tyre references. You can load it again after further tuning.'));
    if (B.drafts[id] && B.drafts[id].donor_baseline) dlg.appendChild(note('A complete donor draft needs its captured baseline on this installation. Export contains settings and references, without game binaries.'));
    dlg.appendChild(input);
    dlg.addEventListener('cancel', function (e) { if (pending) e.preventDefault(); });
    var save = h('button', {class: 'btn', onclick: function () {
      if (pending) return;
      pending = true; dlg.querySelectorAll('button,input').forEach(function (el) { el.disabled = true; });
      run(api('/api/bop/car-setups/capture', 'POST', {car: id, name: input.value, edit: B.drafts[id] || null})
        .then(function (result) { B.carSetup = result.id; dlg.close(); return refreshCarSetups(); })
        .then(function () { render(); toast('Car setup saved.'); })
        .finally(function () { pending = false; dlg.querySelectorAll('button,input').forEach(function (el) { el.disabled = false; }); }), 'Saving this car’s setup…');
    }}, 'Save car setup');
    actions(dlg, save); input.focus();
  }
  function carSetupControls() {
    if (!Array.isArray(B.data.car_setups)) {
      return h('div', {class: 'bop-car-setups'}, h('strong', null, 'This car’s saved setups'), note(carSetupRestartMessage));
    }
    var saved = (B.data.car_setups || []).filter(function (s) { return s.car === B.selected; });
    if (!saved.some(function (s) { return s.id === B.carSetup; })) B.carSetup = '';
    var chooser = h('select', {'aria-label': 'Saved setup for this car', onchange: function () { B.carSetup = chooser.value; render(); }},
      h('option', {value: ''}, saved.length ? 'Choose a car setup…' : 'No saved setups for this car'),
      saved.map(function (s) { return h('option', {value: s.id, selected: s.id === B.carSetup}, s.name); }));
    var imported = h('input', {type: 'file', accept: '.json,application/json', style: {display: 'none'}, 'aria-label': 'Import car setup file', onchange: function () {
      var file = imported.files[0], id = B.selected; if (!file) return;
      if (file.size > 2 * 1024 * 1024) return fail(new Error('Car setups must be smaller than 2 MB.'));
      run(file.text().then(function (text) { return api('/api/bop/car-setups/import', 'POST', {car: id, setup: JSON.parse(text)}); })
        .then(function (result) { B.carSetup = result.id; return refreshCarSetups().then(function () { return stageCarSetup(result); }); }), 'Checking imported car setup…');
    }});
    return h('div', {class: 'bop-car-setups'}, h('label', null, 'This car’s saved setups', chooser),
      h('div', {class: 'bop-car-setup-actions'},
        h('button', {class: 'btn ghost small', onclick: saveCarSetup}, 'Save car setup'),
        h('button', {class: 'btn ghost small', disabled: !B.carSetup, onclick: function () {
          run(api('/api/bop/car-setups/load', 'POST', {car: B.selected, id: B.carSetup}).then(stageCarSetup), 'Loading this car’s setup…');
        }}, 'Load car setup'),
        h('button', {class: 'btn ghost small', disabled: !B.carSetup, onclick: function () {
          run(api('/api/bop/car-setups/file?id=' + encodeURIComponent(B.carSetup)).then(function (setup) {
            var url = URL.createObjectURL(new Blob([JSON.stringify(setup, null, 2)], {type: 'application/json'}));
            h('a', {href: url, download: (setup.car + '_' + setup.name).replace(/[^A-Za-z0-9_-]+/g, '_') + '_car_setup.json'}).click();
            setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
          }), 'Exporting this car’s setup…');
        }}, 'Export car setup'), imported,
        h('button', {class: 'btn ghost small', onclick: function () { imported.click(); }}, 'Import car setup')),
      note('Save installed settings plus this car’s draft. Load or import replaces only this car’s draft; review before applying.'));
  }
  function manageClasses() {
    run(api('/api/bop/class-sets').then(function (data) {
      var dlg = modal('Manage custom classes'), host = h('div', {class: 'bop-class-manager'});
      var M = {data:data, selected:data.classes.length ? data.classes[0].id : '', desired:new Set(),
        search:'', filter:'', busy:false, name:'Testing', base:B.data.classes.some(function(c) {return c.id==='GT3_Gen0';}) ? 'GT3_Gen0' : B.data.classes[0].id, message:''};
      var listHost, selectedHost, summary, reviewButton;
      dlg.classList.add('bop-class-dialog');
      dlg.appendChild(note('Create a class for a test grid, then check cars from any class. Unchecking a member returns it to its remembered original class.'));
      dlg.appendChild(host);
      dlg.addEventListener('cancel', function(e) {if(M.busy) e.preventDefault();});
      function chosen() {return M.data.classes.find(function(c) {return c.id===M.selected;});}
      function resetSelection() {M.desired = new Set(chosen() ? chosen().members : []);}
      function changes() {
        var before = new Set(chosen() ? chosen().members : []);
        return {added:Array.from(M.desired).filter(function(id) {return !before.has(id);}).length,
          removed:Array.from(before).filter(function(id) {return !M.desired.has(id);}).length};
      }
      function visible() {
        return M.data.cars.filter(function(c) {
          return (!M.filter || c.class===M.filter || c.original_class===M.filter) &&
            (!M.search || (c.name+' '+c.id+' '+c.class+' '+(c.original_class||'')).toLowerCase().indexOf(M.search.toLowerCase())>=0);
        }).sort(function(a,b) {return a.name.localeCompare(b.name) || a.id.localeCompare(b.id);});
      }
      function describe(c) {
        return c.class.replace(/_/g,' ') + (c.original_class ? ' · Returns to '+c.original_class.replace(/_/g,' ') : '');
      }
      function rows() {
        var shown = visible(), selected = M.data.cars.filter(function(c) {return M.desired.has(c.id);}), delta=changes();
        summary.textContent=M.desired.size+' selected · '+delta.added+' to add · '+delta.removed+' to restore';
        reviewButton.disabled=M.busy || !M.selected || !(delta.added+delta.removed);
        fill(listHost, shown.length ? shown.map(function(c) {
          var check=h('input', {type:'checkbox', checked:M.desired.has(c.id), disabled:M.busy || !M.selected || !!c.reason,
            'aria-label':'Include '+c.name+' ('+c.id+')', onchange:function() {
              if(check.checked) M.desired.add(c.id); else M.desired.delete(c.id); rows();
            }});
          return h('label', {class:'bop-class-car'+(M.desired.has(c.id)?' selected':''), title:c.id}, check,
            h('span', null, h('b', null, c.name), h('small', null, describe(c)), c.reason ? h('small', {class:'bop-class-error'}, c.reason) : null));
        }) : note('No cars match this search.'));
        fill(selectedHost, selected.length ? selected.sort(function(a,b) {return a.name.localeCompare(b.name);}).map(function(c) {
          return h('div', {class:'bop-class-member'}, h('span', null, h('b', null, c.name), h('small', null, describe(c))),
            h('button', {class:'btn ghost small', disabled:M.busy || !!c.reason, 'aria-label':'Remove '+c.name+' ('+c.id+')',
              onclick:function() {M.desired.delete(c.id); rows();}}, 'Remove'));
        }) : note('Check cars on the left to build this grid.'));
      }
      function task(promise, message) {
        M.busy=true; M.message=message; draw(); setBusy(true, message);
        return promise.catch(function(error) {M.message=error.message || String(error);}).finally(function() {
          M.busy=false; setBusy(false); if(dlg.isConnected) draw();
        });
      }
      function reviewClass() {
        task(api('/api/bop/class-sets/preview', 'POST', {id:M.selected, revision:M.data.revision, members:Array.from(M.desired)}).then(function(plan) {
          M.message='';
          var reviewDlg=modal('Review '+chosen().name+' class'), pending=false;
          reviewDlg.appendChild(note(plan.changes.length+' cars · '+plan.count+' files · '+(plan.backup_bytes/1048576).toFixed(1)+' MB of full-file backups. Close AMS2 and Content Manager before applying.'));
          reviewDlg.appendChild(h('table', {class:'nosort'}, h('thead', null, h('tr', null,
            h('th', null, 'Car'), h('th', null, 'Current class'), h('th', null, 'After apply'))),
            h('tbody', null, plan.changes.map(function(c) {return h('tr', null, h('td', null, c.name),
              h('td', null, c.class_before), h('td', null, c.class_after));}))));
          plan.notes.forEach(function(n) {reviewDlg.appendChild(note(n));});
          reviewDlg.appendChild(h('details', null, h('summary', null, 'Files that will be backed up'),
            h('ul', null, plan.files.map(function(p) {return h('li', null, p);})))) ;
          var status=note(''), apply=h('button', {class:'btn', disabled:!plan.count, onclick:function() {
            pending=true; M.busy=true; apply.disabled=true;
            reviewDlg.querySelectorAll('button').forEach(function(b) {b.disabled=true;});
            setBusy(true, 'Applying class assignments…'); status.textContent='Applying class assignments…';
            api('/api/bop/apply', 'POST', {token:plan.token}).then(function(result) {
              reviewDlg.close(); dlg.close();
              return api('/api/bop').then(function(d) {setData(d, true); persist(); return loadSelection();}).then(function() {
                toast(result.changed+' files updated. Class assignments saved; Undo last apply restores them.');
              });
            }).catch(function(error) {
              status.textContent=error.message || String(error);
              reviewDlg.querySelectorAll('button').forEach(function(b) {b.disabled=false;});
            }).finally(function() {pending=false; M.busy=false; setBusy(false);});
          }}, 'Apply class changes');
          reviewDlg.addEventListener('cancel', function(e) {if(pending) e.preventDefault();});
          reviewDlg.appendChild(status); actions(reviewDlg, apply);
        }), 'Checking class assignments and package capacity…');
      }
      function draw() {
        var selector=h('select', {'aria-label':'Custom class', disabled:M.busy || !M.data.classes.length, onchange:function() {
          M.selected=selector.value; resetSelection(); M.message=''; draw();
        }}, M.data.classes.length ? M.data.classes.map(function(c) {return h('option', {value:c.id, selected:c.id===M.selected}, c.name+' · '+c.members.length+' installed');}) : h('option', null, 'Create your first class below'));
        var name=h('input', {value:M.name, maxlength:80, placeholder:'e.g. Testing', disabled:M.busy, 'aria-label':'New class name', oninput:function() {M.name=name.value;}});
        var base=h('select', {disabled:M.busy, 'aria-label':'Starting class', onchange:function() {M.base=base.value;}},
          B.data.classes.map(function(c) {return h('option', {value:c.id, selected:c.id===M.base}, c.name);}));
        var search=h('input', {type:'search', value:M.search, placeholder:'Find a car…', disabled:M.busy, 'aria-label':'Search cars for custom class', oninput:function() {M.search=search.value; rows();}});
        var classes=Array.from(new Set(M.data.cars.flatMap(function(c) {return [c.class,c.original_class].filter(Boolean);}))).sort();
        var filter=h('select', {disabled:M.busy, 'aria-label':'Filter source class', onchange:function() {M.filter=filter.value; rows();}},
          h('option', {value:''}, 'All source classes'), classes.map(function(c) {return h('option', {value:c, selected:c===M.filter}, c.replace(/_/g,' '));}));
        listHost=h('div', {class:'bop-class-list'}); selectedHost=h('div', {class:'bop-class-list'});
        summary=note(''); summary.setAttribute('role','status');
        reviewButton=h('button', {class:'btn', onclick:reviewClass}, 'Review class changes');
        fill(host, h('label', null, 'Custom class', selector), h('details', {open:!M.data.classes.length}, h('summary', null, 'Create a new class'),
          h('div', {class:'bop-class-create'}, h('label', null, 'New class name', name), h('label', null, 'Use group from', base),
            h('button', {class:'btn ghost', disabled:M.busy, onclick:function() {
              task(api('/api/bop/class-sets', 'POST', {name:M.name,base_class:M.base}).then(function(d) {
                M.data=d; M.selected=d.id; resetSelection(); M.message='Class saved. Choose cars and review to put it in the game.';
              }), 'Saving custom class…');
            }}, 'Create class')), note('The starting class supplies the game grouping. Cars keep their current physics.')),
          h('div', {class:'bop-class-filters'}, search, filter),
          h('div', {class:'bop-class-tools'}, h('button', {class:'btn ghost small', disabled:M.busy || !M.selected, onclick:function() {
            visible().filter(function(c) {return !c.reason;}).forEach(function(c) {M.desired.add(c.id);}); rows();
          }}, 'Add visible cars'), h('button', {class:'btn ghost small', disabled:M.busy || !M.selected, onclick:function() {
            M.data.cars.filter(function(c) {return !c.reason;}).forEach(function(c) {M.desired.delete(c.id);}); rows();
          }}, 'Remove all'), h('button', {class:'btn ghost small', disabled:M.busy || !M.selected, onclick:function() {resetSelection(); rows();}}, 'Reset selection')),
          h('div', {class:'bop-class-columns'}, h('section', null, h('h3', null, 'Available cars'), listHost),
            h('section', null, h('h3', null, chosen() ? chosen().name+' grid' : 'Selected grid'), selectedHost)), summary,
          note(M.message, M.message ? 'warning' : ''), h('div', {class:'actions'},
            h('button', {class:'btn ghost', disabled:M.busy, onclick:function() {dlg.close();}}, 'Close'), reviewButton));
        rows();
      }
      resetSelection(); draw(); dlg.showModal();
    }), 'Loading saved custom classes…');
  }
  function profilesBar() {
    var chooser = h('select', {'aria-label': 'Saved physics profile', onchange: function () { B.profile = chooser.value; render(); }},
      h('option', {value: ''}, 'Saved league profiles'), B.data.profiles.map(function (p) { return h('option', {value: p.id, selected: p.id === B.profile}, p.name + ' · ' + p.cars + ' cars'); }));
    var imported = h('input', {type: 'file', accept: '.json,application/json', style: {display: 'none'}, 'aria-label': 'Import physics profile', onchange: function () {
      var file = imported.files[0]; if (!file) return;
      if (file.size > 2 * 1024 * 1024) return fail(new Error('BOP profiles must be smaller than 2 MB.'));
      run(file.text().then(function (text) { return loadProfile(JSON.parse(text)); }), 'Checking imported profile…');
    }});
    return h('div', {class: 'bop-profile-bar'}, chooser,
      h('button', {class: 'btn ghost small', disabled: !B.profile, onclick: function () {
        run(api('/api/bop/profile?id=' + encodeURIComponent(B.profile)).then(loadProfile), 'Checking saved profile…');
      }}, 'Load draft'),
      h('button', {class: 'btn ghost small', disabled: !B.profile, onclick: function () {
        run(api('/api/bop/profile?id=' + encodeURIComponent(B.profile)).then(function (profile) {
          var url = URL.createObjectURL(new Blob([JSON.stringify(profile, null, 2)], {type: 'application/json'}));
          var link = h('a', {href: url, download: profile.name.replace(/[^A-Za-z0-9_-]+/g, '_') + '_BOP.json'}); link.click();
          setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
        }), 'Exporting profile…');
      }}, 'Export'), imported,
      h('button', {class: 'btn ghost small', onclick: function () { imported.click(); }}, 'Import profile'),
      h('button', {class: 'btn ghost small', disabled: !B.data.classes.length, onclick: manageClasses}, 'Manage classes'),
      h('button', {class: 'btn ghost small', disabled: !B.data.can_undo, onclick: function () {
        var dlg = modal('Undo last apply');
        dlg.appendChild(note('Restores the complete backed-up files from your last physics or class apply. The restore stops if those files have changed since then.'));
        actions(dlg, h('button', {class: 'btn', onclick: function () {
          run(api('/api/bop/undo', 'POST', {}).then(function () {
            dlg.close(); B.drafts = {}; persist();
            return api('/api/bop').then(function (data) { setData(data, true); return loadSelection(); });
          }).then(function () { toast('Last apply restored.'); }), 'Restoring backed-up files…');
        }}, 'Restore files'));
      }}, 'Undo last apply'));
  }
  function render() {
    if (!here() || !B.data) return;
    var host = document.getElementById('bop-body'); if (!host) return;
    var y = document.getElementById('main').scrollTop;
    fill(host, profilesBar(), h('div', {class: 'bop-layout'}, rail(), workspace()), h('div', {id: 'bop-footer', class: 'bop-footer'}),
      B.data.issues.length ? h('details', {class: 'bop-sources'}, h('summary', null, 'Scan issues · ' + B.data.issues.length),
        B.data.issues.map(function (issue) { return note(issue.file + ': ' + issue.message, 'warning'); })) : null,
      B.data.history.length ? h('details', {class: 'bop-sources'}, h('summary', null, 'Apply history'), h('ul', null, B.data.history.map(function (item) {
        return h('li', null, fmtDate(item.created) + ' · ' + item.status + ' · ' + (item.changes || []).map(function (c) { return c.name; }).join(', '));
      }))) : null);
    renderCars(); renderPanel(); footer(); document.getElementById('main').scrollTop = y;
    if (B.busy) {
      // Newly rendered controls also need to remember their own disabled state.
      document.querySelectorAll('.bop-editor button, .bop-editor input, .bop-editor select').forEach(function (el) {
        if (el.dataset.bopDisabled == null) el.dataset.bopDisabled = el.disabled ? '1' : '0'; el.disabled = true;
      });
    }
  }
  return function () {
    var path = h('input', {id: 'bop-game-path', placeholder: 'J:\\SteamLibrary\\steamapps\\common\\Automobilista 2', 'aria-label': 'AMS2 game folder'});
    var scan = h('button', {class: 'btn', onclick: function () {
      run(api('/api/bop/scan', 'POST', {game_path: path.value}).then(function (data) {
        setData(data, true); restore(); persist(); return loadSelection();
      }).then(function () { document.getElementById('bop-status').textContent = B.data.cars.length + ' cars loaded. Select a car and target class to compare.'; }), 'Reading installed car definitions and physics…');
    }}, 'Scan game');
    setView(h('div', {class: 'bop-editor'}, h('div', {class: 'headrow'}, h('div', null, h('p', {class: 'kicker'}, 'League tools'), h('h1', null, converting ? 'Car Conversion' : 'Balance of Performance'),
      h('p', {class: 'sub'}, converting ? 'Change car classes and tune installed physics in 0.25% steps.' : 'Compare performance, fine-tune cars and balance your grid.'))),
      h('div', {class: 'bop-scan'}, h('label', null, 'Automobilista 2 folder', path), scan),
      h('p', {id: 'bop-status', class: 'bop-note', role: 'status'}, 'Scan your game to load its cars, classes and supported physics values.'),
      h('div', {id: 'bop-body'})));
    return api('/api/bop/config').then(function (config) {
      path.value = config.game_path;
      if (config.scanned) return api('/api/bop').then(function (data) { setData(data, true); restore(); persist(); return loadSelection(); });
      if (here()) fill(document.getElementById('bop-body'), h('div', {class: 'bop-empty'}, h('h2', null, 'Build your league’s grid'),
        note(converting ? 'Scan your installed cars, choose a target class and reference car, then select the physics packages to convert.' : 'Scan your installed cars to compare class values, create BOP adjustments, fine-tune parameters and share league profiles.'),
        h('div', {class: 'bop-empty-grid'}, (converting ? ['Choose a target class', 'Select upgrade packages', 'Fine-tune the conversion', 'Review, back up and undo'] : ['Compare installed physics', 'Draft BOP adjustments', 'Fine-tune individual values', 'Review, back up and undo']).map(function (s, i) {
          return h('div', null, h('b', null, '0' + (i + 1)), h('strong', null, s));
        })), note('Actual lap-time balance is checked with recorded tests. Physics values alone cannot predict equal pace.')));
    });
  };
  }
  window.viewBop = createEditor(false);
  window.viewConversion = createEditor(true);
}());
