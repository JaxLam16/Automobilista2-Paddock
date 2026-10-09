/* Championship AI roster and recording-level livery review. */
var IdentityUI = (function () {
  "use strict";
  var pending = {}, seen = {};
  function norm(s) { return String(s || "").toLowerCase().trim().replace(/\s+/g, " "); }
  function className(s) { return norm(String(s || '').replace(/_/g, ' ')); }
  function thumbnail(binding) {
    if (!binding || !binding.livery_id) return null;
    return h('img', {src: binding.image || (binding.preview ? 'data:image/png;base64,' + binding.preview : '/api/liveries/image?car=' + encodeURIComponent(binding.car_id) + '&livery=' + encodeURIComponent(binding.livery_id)),
      alt: (binding.car_name || 'Car') + ' · ' + (binding.livery_name || 'Livery'), title: (binding.car_name || '') + ' · ' + (binding.livery_name || ''),
      loading: 'lazy', style: {width: '64px', height: '36px', objectFit: 'contain', verticalAlign: 'middle', marginRight: '8px'}, onerror: function (e) { e.target.hidden = true; }});
  }
  function rosterThumbnail(cfg, name) {
    var driver = cfg.drivers.find(function (d) { return [d.display, d.key].concat(d.aliases || []).some(function (n) { return norm(n) === norm(name); }); });
    return driver ? thumbnail(driver.livery) : null;
  }
  function replayColor(binding, onChange) {
    var input = h('input', {type: 'color', value: binding.color_override || binding.color || '#E4572E', 'aria-label': 'Replay marker color',
      oninput: function () { binding.color_override = input.value.toUpperCase(); onChange(binding); }});
    var reset = h('button', {type: 'button', class: 'btn ghost small', onclick: function () { delete binding.color_override; input.value = binding.color || '#E4572E'; onChange(binding); }}, 'Use estimated livery color');
    var box = h('div', {class: 'actions', style: {marginTop: '10px'}}, h('label', null, 'Replay marker color ', input), reset,
      h('small', {class: 'hint'}, 'Estimated from the preview when saved; choose a color to override it.'));
    box.refresh = function () { input.disabled = reset.disabled = !binding.livery_id; input.value = binding.color_override || binding.color || '#E4572E'; };
    box.refresh(); return box;
  }
  function image(binding) {
    var src = binding.preview ? "data:image/png;base64," + binding.preview :
      "/api/liveries/image?car=" + encodeURIComponent(binding.car_id) + "&livery=" + encodeURIComponent(binding.livery_id);
    var fallback = h("span", {class: "muted", hidden: true}, "Preview unavailable");
    var img = h("img", {src: src, alt: binding.livery_name || "Livery preview", loading: "lazy", style: {width: "160px", height: "90px", objectFit: "contain"},
      onerror: function () { img.hidden = true; fallback.hidden = false; }});
    return h("div", null, img, fallback);
  }
  function choosePaint(cars, binding, onChange, roster, carClass) {
    var box = h("div"), sel = h("select", {"aria-label": "Catalog car model"});
    var current = cars.find(function (c) { return c.id === binding.car_id; });
    var all = h('input', {type: 'checkbox', checked: false, onchange: function () { options(); }});
    function options() {
    current = cars.find(function (c) { return c.id === binding.car_id; });
    var allowed = cars.filter(function (c) { return !carClass || all.checked || className(c.class) === className(carClass); });
    fill(sel, h("option", {value: ""}, "Choose catalog car model"), allowed.map(function (c) {
      return h("option", {value: c.id, selected: c.id === binding.car_id}, c.name + (c.class ? " · " + c.class : ""));
    }));
    if (binding.car_id && !allowed.some(function (c) { return c.id === binding.car_id; })) sel.appendChild(h("option", {value: binding.car_id, selected: true}, (binding.car_name || (current && current.name) || binding.car_id) + (current ? " (selected outside class)" : " (saved catalog)")));
    }
    options();
    var paints = h("div", {style: {display: "flex", flexWrap: "wrap", gap: "8px", maxHeight: "230px", overflowY: "auto", marginTop: "10px"}});
    function draw() {
      var car = cars.find(function (c) { return c.id === binding.car_id; });
      var rows = car ? car.liveries.map(function (p) {
        return binding.livery_id === p.id && binding.livery_name ? Object.assign({}, p, {name: binding.livery_name}) : p;
      }) : [];
      if (binding.livery_id && !rows.some(function (p) { return p.id === binding.livery_id; })) rows.push({id: binding.livery_id, name: binding.livery_name || binding.livery_id});
      fill(paints, rows.length ? null : h("p", {class: "hint"}, "Choose a car to see its liveries."), rows.map(function (p) {
        var selected = binding.livery_id === p.id;
        var b = {car_id: binding.car_id, livery_id: p.id, livery_name: p.name, preview: selected ? binding.preview : null};
        var driver = (roster || []).find(function (d) { var l = d.livery || {}; return l.car_id === b.car_id && l.livery_id === b.livery_id; });
        return h("button", {type: "button", class: "btn ghost small", "aria-pressed": String(selected),
          style: {display: 'flex', flexDirection: 'column', alignItems: 'stretch', gap: '4px', width: "184px", flexShrink: '0',
            whiteSpace: "normal", textAlign: 'left', border: selected ? "2px solid var(--green)" : "1px solid var(--line)"},
          onclick: function () { binding.livery_id = p.id; binding.livery_name = p.name; if (!selected) { delete binding.preview; delete binding.color; delete binding.color_override; } onChange(binding); draw(); }},
          image(b), h("div", null, p.name + " (#" + p.id + ")"), driver ? h("b", null, driver.display) : null);
      }));
    }
    sel.addEventListener("change", function () {
      var car = cars.find(function (c) { return c.id === sel.value; });
      binding.car_id = sel.value; binding.car_name = car ? car.name : "";
      binding.livery_id = ""; binding.livery_name = ""; delete binding.preview; delete binding.color; delete binding.color_override;
      onChange(binding); draw();
    });
    box.redraw = draw; fill(box, carClass ? h('label', {class: 'check'}, all, 'Show all classes') : null, sel, paints); draw(); return box;
  }
  function editor(cfg) {
    var box = h("section", null, h("div", {class: "panel pad"}, h("h3", null, "Fictional AI drivers"), h("p", {class: "hint"}, "Loading installed livery catalog…")));
    var catalog = {cars: [], recorded_models: []};
    function draw() {
      var enabled = h("input", {type: "checkbox", checked: !!cfg.livery_ai, onchange: function () { cfg.livery_ai = enabled.checked; }});
      var list = h("div");
      var modelsId = "identity-recorded-models";
      var models = h("datalist", {id: modelsId}, catalog.recorded_models.map(function (m) { return h("option", {value: m}); }));
      fill(list, cfg.drivers.map(function (driver) {
        var binding = driver.livery || (driver.livery = {});
        var previousModel = binding.car_name;
        var preview = h('span', null, thumbnail(binding));
        var description = h('span', null, ' · ' + (binding.car_name || 'choose car') + ' · ' + (binding.livery_name || 'choose livery'));
        var model = h("input", {type: "text", list: modelsId, value: binding.recorded_car || "", placeholder: "Car name in recordings", "aria-label": "Recorded car model",
          oninput: function () { binding.recorded_car = model.value; }});
        var picker = choosePaint(catalog.cars, binding, function () {
          if (!binding.recorded_car || norm(binding.recorded_car) === norm(previousModel)) {
            binding.recorded_car = catalog.recorded_models.find(function (m) { return norm(m) === norm(binding.car_name); }) || binding.car_name;
            model.value = binding.recorded_car || "";
          }
          previousModel = binding.car_name;
          fill(preview, thumbnail(binding));
          description.textContent = ' · ' + (binding.car_name || 'choose car') + ' · ' + (binding.livery_name || 'choose livery');
          if (colors) colors.refresh();
        }, null, cfg.car_class);
        var colors = replayColor(binding, function () {});
        return h("details", {class: "panel pad", open: !driver.display, style: {marginTop: "12px"}},
          h("summary", null, preview, h("b", null, driver.display || (driver.role === 'ai' ? "New fictional AI" : 'New human friend')), driver.role === 'ai' ? ' · AI' : ' · Human friend', description),
          driver.role === 'ai' ? h("label", {class: "field"}, h("span", null, "Fictional driver name"), h("input", {type: "text", value: driver.display || "", "aria-label": "Fictional driver name", oninput: function (e) { driver.display = e.target.value; }})) : null,
          h("label", {class: "field"}, h("span", null, "Recorded car model (use the exact name shown in a recording)"), model), picker,
          colors,
          driver.role === 'ai' ? h("button", {class: "btn ghost small", type: "button", style: {marginTop: "12px"}, onclick: function () { cfg.drivers.splice(cfg.drivers.indexOf(driver), 1); draw(); }}, "Remove fictional AI") :
            h('button', {class: 'btn ghost small', type: 'button', onclick: function () { delete driver.livery; draw(); }}, 'Clear human car/livery'));
      }));
      var classes = Array.from(new Set(catalog.cars.map(function (c) { return c.class; }).filter(Boolean).concat(cfg.car_class ? [cfg.car_class] : []))).sort();
      var classSelect = h('select', {'aria-label': 'Championship car class', onchange: function (e) { cfg.car_class = e.target.value; draw(); }}, h('option', {value: '', selected: !cfg.car_class}, 'All classes'),
        classes.map(function (c) { return h('option', {value: c, selected: cfg.car_class === c}, c); }));
      fill(box, h("div", {class: "panel pad"}, h("h3", null, "Driver cars and liveries"),
        h("p", {class: "explain"}, "Choose liveries for human friends and fictional AI. Human names and roles stay intact. Enable race assignments to review liveries once per race. Choose Full field scoring above if fictional AI should earn championship points."),
        h('label', {class: 'field'}, h('span', null, 'Championship car class'), classSelect, h('small', null, 'Filters car choices in this roster and race assignments. Existing selections are retained.')),
        h("label", {class: "check"}, enabled, "Enable race livery assignments (including AI identities)"),
        catalog.cars.length ? null : h("p", {class: "hint"}, "Scan your AMS2 installation in the Livery editor to populate car and livery choices."),
        catalog.problem ? h('p', {class: 'hint'}, 'Current catalog unavailable: ' + catalog.problem + ' Saved livery selections remain available.') : null,
        models, list,
        h("button", {class: "btn ghost small", type: "button", style: {marginTop: "12px"}, onclick: function () {
          cfg.drivers.push({key: "ai-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 7), role: "ai", display: "", aliases: [], livery: {}});
          cfg.livery_ai = true; draw();
        }}, "Add fictional AI driver")));
    }
    box.refresh = draw;
    api("/api/identities/catalog").then(function (c) { catalog = c; draw(); }).catch(function (e) { draw(); box.appendChild(h("p", {class: "lose"}, e.message)); });
    return box;
  }
  function review(recording, champ, data) {
    return api("/api/identities/catalog").catch(function (e) { toast("Catalog unavailable: " + e.message, {error: true}); return {cars: []}; }).then(function (catalog) {
      return new Promise(function (resolve) {
        var dlg = document.getElementById("dlg"), selected = {}, err = h("p", {class: "lose"});
        var cards = data.entrants.map(function (entrant) {
          var human = !entrant.is_ai && data.drivers.find(function (d) { return d.role !== 'ai' && [d.display, d.key].concat(d.aliases || []).some(function (n) { return norm(n) === norm(entrant.name); }); });
          var defaultPaint = human && human.livery && norm(human.livery.recorded_car) === norm(entrant.car) ? human.livery : null;
          var saved = data.assignments[entrant.id] || (!data.reviewed ? defaultPaint : null);
          selected[entrant.id] = saved ? Object.assign({}, saved) : null;
          var candidates = data.drivers.filter(function (d) { return d.role === "ai" && norm((d.livery || {}).recorded_car) === norm(entrant.car); });
          var binding = saved ? Object.assign({}, saved) : {car_id: candidates.length ? candidates[0].livery.car_id : "", recorded_car: entrant.car};
          if (!binding.car_id) { var matching = catalog.cars.find(function (c) { return norm(c.name) === norm(entrant.car); }); if (matching) binding.car_id = matching.id; }
          var preview = h('span', null, thumbnail(saved));
          var status = h("p", {class: "hint"}, saved ? (saved.livery_name + " (#" + saved.livery_id + ")" + (defaultPaint && !data.assignments[entrant.id] ? ' · roster default, confirm for this race' : '')) : "Unknown / skip for now");
          var picker = choosePaint(catalog.cars, binding, function (value) {
            selected[entrant.id] = value.livery_id ? Object.assign({}, value, {recorded_car: entrant.car}) : null;
            fill(preview, thumbnail(selected[entrant.id]));
            if (colors) colors.refresh();
            var driver = candidates.find(function (d) { return d.livery.car_id === value.car_id && d.livery.livery_id === value.livery_id; });
            status.textContent = value.livery_id ? (value.livery_name + (driver && entrant.is_ai ? " → " + driver.display : "")) : "Unknown / skip for now";
          }, candidates, data.car_class);
          var colors = replayColor(binding, function (value) { if (selected[entrant.id]) selected[entrant.id] = Object.assign({}, value, {recorded_car: entrant.car}); });
          return h("details", {class: "panel pad", style: {marginTop: "10px"}},
            h("summary", null, preview, h("b", null, "P" + entrant.finish + " · " + entrant.name), " · " + entrant.car + " · " + entrant.status + (entrant.is_ai ? " · AI" : " · Human friend")), status,
            h("p", {class: "hint"}, "Confirm which installed model corresponds to “" + entrant.car + "”, then select its observed livery."),
            entrant.is_ai && !candidates.length ? h('p', {class: 'hint'}, 'No fictional driver is configured for this recorded car name. Set its Recorded car model in championship Settings if you expected one.') : null, picker,
            colors,
            h("button", {class: "btn ghost small", type: "button", onclick: function () { selected[entrant.id] = null; binding.livery_id = ""; delete binding.preview; fill(preview); colors.refresh(); status.textContent = "Unknown / skip for now"; picker.redraw(); }}, "Unknown / clear assignment"));
        });
        var button = h("button", {class: "btn", type: "submit"}, "Save assignments");
        var form = h("form", {onsubmit: function (event) {
          event.preventDefault(); err.textContent = ""; button.disabled = true;
          api("/api/identities", "POST", {recording: recording, champ: champ, revision: data.revision, assignments: selected}).then(function (result) {
            (result.problems || []).forEach(function (p) { toast(p, {error: true}); });
            toast("Liveries saved. Unknown entries keep their recorded names."); dlg.close();
          }).catch(function (e) { err.textContent = e.message; }).finally(function () { button.disabled = false; });
        }}, h("h2", null, "Assign race liveries"),
          h("p", {class: "explain"}, data.champ_name + ": match these original recorded entrants to the liveries you observed in AMS2. Use a game replay or screenshot; telemetry cannot show the paint. Unknowns are allowed and this review is saved once per recording."),
          h("p", {class: "hint"}, "Finish order includes retired and disconnected cars. Human names and roles stay intact. Expand a row to see livery pictures."),
          cards, err, h("div", {class: "actions", style: {marginTop: "14px"}},
            h("button", {class: "btn ghost", type: "button", onclick: function () { dlg.close(); }}, "Review later"), button));
        var width = dlg.style.width, max = dlg.style.maxWidth;
        dlg.style.width = "min(1040px, 94vw)"; dlg.style.maxWidth = "1040px";
        fill(dlg, form);
        dlg.addEventListener("close", function done() { dlg.removeEventListener("close", done); dlg.style.width = width; dlg.style.maxWidth = max; resolve(); });
        dlg.showModal();
      });
    });
  }
  function ensure(recording, champ, force) {
    var key = recording + "|" + (champ || '');
    if (pending[key]) return pending[key];
    if (seen[key] && !force) return Promise.resolve(seen[key].champ);
    pending[key] = api("/api/identities?recording=" + encodeURIComponent(recording) + (champ ? "&champ=" + encodeURIComponent(champ) : '') + (force ? "&detail=1" : ""))
      .then(function (data) {
        var dlg = document.getElementById("dlg");
        var wait = dlg.open ? new Promise(function (resolve) { dlg.addEventListener("close", resolve, {once: true}); }) : Promise.resolve();
        if (data.choices && data.choices.length && !data.reviewed) {
          return wait.then(function () { return new Promise(function (resolve) {
            var chosen = null, sel = h('select', null, data.choices.map(function (c) { return h('option', {value: c.id}, c.name); }));
            dlg.addEventListener('close', function closed() { dlg.removeEventListener('close', closed); resolve(chosen); });
            dialog('Choose a championship roster', [h('p', {class: 'explain'}, 'This recording can use different fictional AI names in each championship. Choose the roster to review it with.'), sel], function () { chosen = sel.value; }, 'Use roster');
          }); }).then(function (selected) {
            if (!selected) { seen[key] = {champ: null}; return null; }
            return ensure(recording, selected, force);
          });
        }
        if (!data.enabled) {
          if (!force) return data.champ;
          return wait.then(function () {
            return new Promise(function (resolve) {
              dlg.addEventListener('close', function closed() { dlg.removeEventListener('close', closed); resolve(data.champ); });
              if (data.setup_required && data.champ) {
                dialog('Set up race livery assignments', [h('p', {class: 'explain'}, 'In this championship’s Settings, choose car/livery bindings for human friends or fictional AI, check Enable race livery assignments, then Save changes. Return to this race to match the recorded entrants to their livery pictures.')],
                  function () { location.hash = '#/champ/' + encodeURIComponent(data.champ) + '/settings'; }, 'Open championship Settings');
              } else {
                dialog('Livery assignments unavailable', [h('p', {class: 'explain'}, data.unavailable_reason || 'Open this completed race from a championship with a fictional AI roster.')], function () {}, 'OK');
              }
            });
          });
        }
        if (data.reviewed && !force) return data.champ;
        return wait.then(function () { seen[key] = {champ: data.champ}; return review(recording, data.champ, data); }).then(function () { return data.champ; });
      }).finally(function () { delete pending[key]; });
    return pending[key];
  }
  return {editor: editor, ensure: ensure, thumbnail: thumbnail, rosterThumbnail: rosterThumbnail};
})();
