/* Championship weekends, telemetry development projects and season trends. */
window.AMS2CampaignUI = function (ui) {
  "use strict";
  var h = ui.h, svg = ui.svg, api = ui.api;
  var fail = ui.fail, toast = ui.toast, render = ui.render;
  var field = function (label, control) { return h("label", {class: "field"}, h("span", null, label), control); };
  var url = function (id) { return "/api/championships/" + encodeURIComponent(id); };
  var link = function (id, tab, label) { return h("a", {class: "btn ghost small", href: "#/champ/" + id + "/" + tab}, label); };
  function slotsDialog(d, id, w) {
    w = w || {round: Math.max(0, ...(d.weekends || []).map(function (x) { return x.round; })) + 1};
    return api("/api/recordings").then(function (R) {
      var round = h("input", {type: "number", min: 1, max: 999, value: w.round, required: true, disabled: !!w.sessions});
      var name = h("input", {value: w.name || "", placeholder: "Optional weekend name"});
      function pick(role, type) {
        return h("select", {"aria-label": role}, h("option", {value: ""}, "Not assigned yet"),
          R.recordings.filter(function (r) { return r.type === type; }).map(function (r) {
            return h("option", {value: r.id, selected: w[role] === r.id}, r.track + " · " + ui.fmtDate(r.started_at) + " · " + (r.driver || ""));
          }));
      }
      var p1 = pick("practice1", "practice"), p2 = pick("practice2", "practice"), race = pick("race", "race"), quali = pick("qualify", "qualify");
      var locked = (w.development || []).length > 0;
      p1.disabled = locked;
      var known = R.recordings.find(function (r) { return r.id === w.race; });
      if (!w.qualify && known && known.quali) quali.value = known.quali;
      race.addEventListener("change", function () { var r = R.recordings.find(function (x) { return x.id === race.value; }); if (r && r.quali) quali.value = r.quali; });
      ui.dialog("Weekend recordings", [field("Weekend", round), field("Name", name),
        h("div", {class: "campaign-grid"}, field("Practice 1 · setup and track learning", p1), field("Practice 2 · development test", p2)),
        h("p", {class: "hint"}, "Practice 1 stays out of season ratings and championship points. Choose your R&D goals after P1 and before assigning P2."),
        h("h3", null, "Qualifying + race"), field("Race recording", race), field("Paired qualifying recording", quali),
        h("p", {class: "hint"}, "Keep the recorder running through qualifying and the race. AMS2 records each session separately; they appear together as one weekend entry here.")
      ], function () {
        return api(url(id) + "/weekends", "POST", {round: Number(round.value), name: name.value, practice1: p1.value, practice2: p2.value, race: race.value, qualify: quali.value})
          .then(function () { toast("Weekend recordings saved."); render(); ui.refreshNav(); });
      }, "Save weekend");
    }).catch(fail);
  }
  function weekendSection(d, id) {
    var rows = d.weekends || [];
    function slot(w, role, title, text) {
      var r = (w.sessions || {})[role];
      return h("div", {class: "campaign-slot"}, h("p", {class: "kicker"}, title), h("p", {class: "hint"}, text),
        r ? h("div", null, h("b", null, r.missing ? "Recording missing" : ui.fmtDate(r.started_at)), h("p", {class: "muted campaign-file"}, r.id),
          !r.missing ? h("div", {class: "actions"}, h("a", {class: "btn ghost small", href: "#/" + (role === "race" ? "race" : role === "qualify" ? "quali" : "technique") + "/" + encodeURIComponent(r.id) + "?champ=" + id}, "Open analysis"),
            role === "practice1" && r.car ? h("button", {class: "btn ghost small", onclick: function () {
              api("/api/engineer/session", "POST", {car: r.car, track: r.track_raw, layout: r.layout_raw})
                .then(function (s) { location.hash = "#/engineer/" + encodeURIComponent(s.key); }).catch(fail);
            }}, "Set up with engineer") : null) : null)
          : h("p", {class: "muted"}, "Not assigned yet"));
    }
    return h("section", null, h("div", {class: "headrow", style: {marginTop: "24px"}}, h("div", null, h("h2", null, "Race weekends"),
      h("p", {class: "explain"}, "Learn and set up the car in P1, lock two development areas, test their objectives in P2, then qualify and race.")),
      h("button", {class: "btn", onclick: function () { slotsDialog(d, id); }}, "Add weekend")),
      h("div", {class: "actions", style: {marginBottom: "16px"}}, link(id, "development", "Open R&D"),
        h("a", {class: "btn ghost small", href: "#/recordings"}, "Import recordings")),
      rows.length ? rows.map(function (w) {
        return h("article", {class: "panel pad campaign-weekend"}, h("div", {class: "headrow"}, h("div", null,
          h("h3", null, "Weekend " + w.round + (w.name ? " · " + w.name : "")), h("p", {class: "muted"}, (w.track || "Track not assigned").replace(/_/g, " "))),
          h("div", {class: "actions"}, h("button", {class: "btn ghost small", onclick: function () { slotsDialog(d, id, w); }}, "Assign recordings"), link(id, "development", "R&D"))),
          h("div", {class: "campaign-weekend-grid"}, slot(w, "practice1", "01 / Practice 1", "Engineer setup and a 3-lap reference."),
            slot(w, "practice2", "02 / Practice 2", "Test your locked development objectives."),
            h("div", {class: "campaign-slot"}, h("p", {class: "kicker"}, "03 / Qualifying + race"),
              slot(w, "qualify", "Qualifying", "Grid preparation."), slot(w, "race", "Race", "Points and season ratings."))));
      }) : h("div", {class: "panel pad"}, h("h3", null, "Start a weekend"), h("p", {class: "muted"}, "Assign a Practice 1 recording, then choose what to develop in R&D.")));
  }
  function developmentSection(d, id) {
    var box = h("section", {class: "campaign-development"}, h("div", {class: "spinner"}, "Loading development projects..."));
    var selected = new Set(), currentRound = null, alive = true, timer = null;
    ui.state.cleanup = function () { alive = false; if (timer) clearInterval(timer); };
    function refresh() { return api(url(id) + "/development").then(function (D) { if (alive) draw(D); }).catch(fail); }
    function action(path, body, message) {
      return api(url(id) + "/development/" + path, "POST", body).then(function () { if (path === "plan") selected.clear(); if (message) toast(message); return refresh(); }).catch(fail);
    }
    function draw(D) {
      var cfg = D.config, available = D.catalog.filter(function (c) { return c.available; });
      var path = h("input", {value: D.physics.game_path || "", placeholder: "C:\\...\\Automobilista 2", "aria-label": "AMS2 installation folder"});
      var car = h("select", {"aria-label": "Championship development car"}, h("option", {value: ""}, "Choose installed car"),
        D.cars.map(function (c) { return h("option", {value: c.id, selected: cfg.car === c.id}, c.name + " · " + c.class); }));
      var auto = h("input", {type: "checkbox", checked: cfg.automatic !== false});
      var telemetryName = h("input", {value: cfg.telemetry_car || "", placeholder: "Use installed car name", "aria-label": "Telemetry car name"});
      var binding = h("details", {class: "panel pad", open: !cfg.car || !D.physics.scanned}, h("summary", null, h("b", null, "Installed car"),
        cfg.name ? " · " + cfg.name : " · choose your development car"),
        h("div", {class: "formgrid", style: {marginTop: "16px"}}, field("AMS2 installation folder", path), h("button", {class: "btn ghost", onclick: function () {
          api("/api/bop/scan", "POST", {game_path: path.value}).then(refresh).catch(fail);
        }}, "Scan installed cars")),
        field("Championship car", car), field("Car name in telemetry (if different)", telemetryName),
        h("label", {class: "check"}, auto, "Automatically apply earned upgrades when AMS2 is closed"),
        h("button", {class: "btn", onclick: function () { action("configure", {car: car.value, telemetry_car: telemetryName.value, automatic: auto.checked}, "Development car saved."); }}, "Use this installed car"));
      var choices = D.weekends.filter(function (w) { return w.practice1 && !w.practice2 && !w.development.length; });
      if (!choices.some(function (w) { return w.round === currentRound; })) currentRound = choices.length ? choices[0].round : null;
      var week = h("select", {"aria-label": "Development weekend", onchange: function (e) { currentRound = Number(e.target.value); }},
        choices.map(function (w) { return h("option", {value: w.round, selected: currentRound === w.round}, "Weekend " + w.round + " · " + (w.track || "").replace(/_/g, " ")); }));
      var planButton = h("button", {class: "btn", disabled: !cfg.car || !choices.length || !selected.size, onclick: function () {
        action("plan", {round: Number(week.value), categories: Array.from(selected)}, "Development objectives locked for Practice 2.").then(function () { selected.clear(); });
      }}, "Lock Practice 2 objectives");
      var catalog = h("div", {class: "campaign-catalog"}, D.catalog.map(function (c) {
        var inp = h("input", {type: "checkbox", checked: selected.has(c.id), disabled: !c.available || c.unlocked >= c.max_level || !choices.length,
          "aria-label": "Develop " + c.name, onchange: function () {
            if (inp.checked && selected.size >= 2) { inp.checked = false; toast("Choose up to two development areas."); return; }
            if (inp.checked) selected.add(c.id); else selected.delete(c.id);
            planButton.disabled = !selected.size || !cfg.car || !choices.length;
          }});
        return h("label", {class: "panel pad campaign-category" + (!c.available ? " campaign-unavailable" : "")},
          h("div", {class: "headrow"}, h("b", null, c.name), inp), h("p", {class: "hint"}, c.description),
          h("p", {class: "muted"}, c.applied + "/" + c.max_level + " levels applied · " + c.unlocked + " unlocked"),
          h("progress", {max: c.max_level, value: c.applied, "aria-label": c.name + " progress"}),
          c.points % 2 ? h("p", {class: "hint"}, "1 research point towards the next upgrade.") : null,
          c.reason ? h("p", {class: "hint"}, c.reason) : null);
      }));
      var plans = D.plans.map(function (p) {
        var w = D.weekends.find(function (x) { return x.round === p.round; });
        var evaluation = p.evaluation, passed = evaluation ? evaluation.projects.reduce(function (n, x) { return n + x.points; }, 0) : null;
        var rows = evaluation ? evaluation.projects : p.projects;
        var controls = [];
        if (!evaluation && w && w.practice2) controls.push(h("button", {class: "btn", onclick: function () { action("submit", {plan: p.id}, "Practice 2 assessed."); }}, "Assess Practice 2 and award upgrades"));
        if (!evaluation && w && !w.practice2) controls.push(h("button", {class: "btn ghost small", onclick: function () { slotsDialog(d, id, w); }}, "Assign Practice 2 recording"));
        if (p.state === "blocked") controls.push(h("button", {class: "btn ghost small", onclick: function () { action("retry", {plan: p.id}, "Upgrade checked."); }}, "Retry application"),
          h("button", {class: "btn ghost small", onclick: function () {
            ui.dialog("Adopt the current physics", h("p", null, "This keeps your earned upgrade and applies its small changes to the car currently installed. Review any intervening BOP or conversion changes first."),
              function () { return action("retry", {plan: p.id, adopt_current: true}); }, "Adopt and apply");
          }}, "Adopt current car and retry"));
        if (p.state === "queued" && cfg.automatic === false) controls.push(h("button", {class: "btn", onclick: function () { action("retry", {plan: p.id}); }}, "Apply earned upgrades"));
        if (p.state === "applied") controls.push(h("button", {class: "btn ghost small", onclick: function () {
          ui.dialog("Undo this upgrade", h("p", null, "Restore the backed-up game files for this upgrade. The latest physics transaction can be undone; unlocked research stays in your season history."),
            function () { return action("undo", {plan: p.id}, "Physics upgrade restored from backup."); }, "Undo upgrade");
        }}, "Undo latest upgrade"));
        return h("article", {class: "panel pad campaign-plan"}, h("div", {class: "headrow"}, h("h3", null, "Weekend " + p.round + " development"), h("span", {class: "badge"}, p.state)),
          h("p", {class: "muted"}, p.driver + " · " + p.car_name + " · P1 reference " + ui.lapTime(p.baseline.median) + " from laps " + p.baseline.reference_laps.join(", ")),
          h("div", {class: "campaign-grid"}, rows.map(function (x) {
            var c = D.catalog.find(function (c) { return c.id === x.category; });
            return h("div", null, h("h4", null, c ? c.name : x.category), h("ul", {class: "tips"}, x.objectives.map(function (o) {
              return h("li", null, o.passed === true ? "✓ " : o.passed === false ? "○ " : "", o.text,
                o.actual != null ? h("span", {class: "muted"}, " Measured: " + o.actual + (o.laps.length ? " · laps " + o.laps.join(", ") : "")) : o.passed === false ? " No eligible sample." : "");
            })));
          })),
          evaluation ? h("p", null, passed + " objective" + (passed === 1 ? "" : "s") + " met · " + Object.values(p.upgrades).reduce(function (a, b) { return a + b; }, 0) + " upgrade levels earned.") : null,
          p.error ? h("p", {class: "muted"}, p.error) : null,
          p.physics_changes ? h("details", null, h("summary", null, "Applied physics changes"), p.physics_changes.map(function (c) {
            return h("ul", {class: "tips"}, c.parameters.map(function (v) { return h("li", null, v.parameter + ": " + Number(v.before).toPrecision(6) + " → " + Number(v.after).toPrecision(6) + " " + v.unit); }));
          })) : null,
          p.transaction ? h("p", {class: "hint campaign-file"}, "Transaction " + p.transaction) : null,
          h("div", {class: "actions", style: {marginTop: "12px"}}, controls));
      });
      box.replaceChildren(h("div", {class: "headrow", style: {marginTop: "24px"}}, h("div", null, h("h2", null, "Research & development"),
        h("p", {class: "explain"}, "Two areas per weekend. Each completed objective earns a research point; every two points unlock one small upgrade, up to eight levels per area. Partial credit carries through the season.")), link(id, "rounds", "Weekend recordings")),
        h("p", {class: "hint"}, "Rewards modify the installed car’s physics. Game files are backed up; queued upgrades apply after AMS2 closes. These are campaign rewards, and do not promise a particular lap-time improvement."), binding,
        plans.length ? h("section", null, h("h3", null, "Your development programme"), plans) : null,
        h("div", {class: "headrow", style: {margin: "24px 0 16px"}}, h("div", null, h("h3", null, "Choose your next development areas"),
          h("p", {class: "hint"}, available.length + " areas supported by this installed car.")), choices.length ? week : null),
        !choices.length ? h("p", {class: "muted"}, "Assign P1 to a new weekend before choosing its development areas.") : null,
        catalog, h("div", {class: "actions", style: {marginTop: "18px"}}, planButton));
      var pending = D.plans.some(function (p) { return p.state === "queued" || p.state === "applying"; });
      if (pending && !timer) timer = setInterval(refresh, 5000);
      if (!pending && timer) { clearInterval(timer); timer = null; }
    }
    refresh(); return box;
  }
  function metricTable(P, p) {
    return h("div", {class: "panel scroll campaign-metrics"}, h("table", null, h("thead", null, h("tr", null,
      ["Season metric", "Score", "Races measured"].map(function (x) { return h("th", null, x); }))),
      h("tbody", null, P.dimensions.map(function (dim) {
        var value = p.scores[dim.key];
        return h("tr", null, h("td", {title: dim.about}, dim.label), h("td", {class: "num"}, value == null ? "No data" : h("b", null, value + "/100")),
          h("td", {class: "num muted"}, p.samples ? p.samples[dim.key] : p.races));
      }))));
  }
  function trendsSection(d, id) {
    var box = h("section", null, h("div", {class: "spinner"}, "Loading season history..."));
    api(url(id) + "/profiles").then(function (P) {
      if (!P.profiles.length) { box.replaceChildren(h("p", null, "File a race to start tracking season metrics.")); return; }
      var driver = P.profiles[0].key, metric = "consistency", mode = "race";
      var ds = h("select", {"aria-label": "Trend driver", onchange: function () { driver = ds.value; draw(); }}, P.profiles.map(function (p) { return h("option", {value: p.key}, p.driver); }));
      var ms = h("select", {"aria-label": "Trend metric", onchange: function () { metric = ms.value; draw(); }}, P.dimensions.map(function (dim) { return h("option", {value: dim.key, selected: dim.key === metric}, dim.label); }));
      var modeSelect = h("select", {"aria-label": "Trend aggregation", onchange: function () { mode = modeSelect.value; draw(); }}, h("option", {value: "race"}, "Each race"), h("option", {value: "season"}, "Season to date"));
      var body = h("div");
      function draw() {
        var p = P.profiles.find(function (p) { return p.key === driver; }), points = p.history, history = [];
        var rawKeys = Object.keys(p.raw), cumulative = {};
        // Backend supplies cumulative scores so charts use the same score formulas as the profile.
        points.forEach(function (pt) { history.push(mode === "season" ? (pt.cumulative_scores || {})[metric] : pt.scores[metric]); });
        var width = 760, height = 270, left = 42, right = 20, top = 20, bottom = 35;
        var chart = svg("svg", {viewBox: "0 0 760 270", width: "100%", role: "img", "aria-label": "Season " + metric + " trend"});
        var x = function (i) { return left + (points.length < 2 ? (width - left - right) / 2 : i * (width - left - right) / (points.length - 1)); };
        var y = function (v) { return height - bottom - v / 100 * (height - top - bottom); };
        [0, 25, 50, 75, 100].forEach(function (v) {
          chart.appendChild(svg("line", {x1: left, x2: width - right, y1: y(v), y2: y(v), stroke: "var(--line)"}));
          chart.appendChild(svg("text", {x: left - 10, y: y(v) + 4, "text-anchor": "end", fill: "var(--muted)", "font-size": 12}, String(v)));
        });
        var segment = [];
        function flush() { if (segment.length) chart.appendChild(svg("polyline", {points: segment.join(" "), fill: "none", stroke: p.color || "var(--accent)", "stroke-width": 3})); segment = []; }
        points.forEach(function (pt, i) {
          var v = history[i];
          if (v == null) flush(); else {
            segment.push(x(i) + "," + y(v));
            var dot = svg("circle", {cx: x(i), cy: y(v), r: 5, fill: p.color || "var(--accent)"});
            var start = pt.start || {};
            dot.appendChild(svg("title", {}, pt.label + " · " + pt.track + " · " + v + "/100" +
              (metric === "starts" && start.grid != null && start.lap1_pos != null ? " · Grid P" + start.grid + " → lap one P" + start.lap1_pos + " of " + start.field_size : ""))); chart.appendChild(dot);
          }
          if (points.length < 15 || i % Math.ceil(points.length / 12) === 0) chart.appendChild(svg("text", {x: x(i), y: height - 10, "text-anchor": "middle", fill: "var(--muted)", "font-size": 12}, pt.label));
        }); flush();
        var rated = history.filter(function (x) { return x != null; }), change = rated.length > 1 ? rated[rated.length - 1] - rated[0] : null;
        body.replaceChildren(h("div", {class: "panel pad"}, h("h3", null, p.driver + " · " + P.dimensions.find(function (x) { return x.key === metric; }).label),
          h("p", {class: "muted"}, change == null ? "One measured race starts the history; another shows a trend." : (change > 0 ? "+" : "") + change + " points from first to latest measured race."),
          metric === "starts" ? h("p", {class: "explain"}, "Holding position scores 50; holding pole scores 100. Gains and losses are scaled by the positions available ahead and behind. Season scores average each measured race; missing starts stay unrated.") : null, chart),
          h("div", {class: "panel scroll", style: {marginTop: "16px"}}, h("table", null,
            h("thead", null, h("tr", null, ["Race", "Track", "Score", "Average lap", "Best lap"].concat(metric === "starts" ? ["Start → lap one"] : []).map(function (v) { return h("th", null, v); }))),
            h("tbody", null, points.map(function (pt, i) { return h("tr", null, h("td", null, pt.label), h("td", null, pt.track.replace(/_/g, " ")),
              h("td", {class: "num"}, history[i] == null ? "No data" : history[i] + "/100"), h("td", {class: "num"}, ui.lapTime(pt.average_lap)), h("td", {class: "num"}, ui.lapTime(pt.best_lap)),
              metric === "starts" ? h("td", {class: "num"}, !pt.start || pt.start.grid == null || pt.start.lap1_pos == null ? "No data" : "P" + pt.start.grid + " → P" + pt.start.lap1_pos + " / " + pt.start.field_size) : null); })))));
      }
      box.replaceChildren(h("h2", {style: {marginTop: "24px"}}, "Season metric trends"), h("p", {class: "explain"}, "Compare the same 0–100 measurements across tracks. Choose individual races or your season-to-date rating. Practice 1 is excluded; Practice 2 development stays in your R&D history."),
        h("div", {class: "actions", style: {marginBottom: "16px"}}, ds, ms, modeSelect), body);
      draw();
    }).catch(fail); return box;
  }
  return {weekends: weekendSection, development: developmentSection, trends: trendsSection, metricTable: metricTable};
};
