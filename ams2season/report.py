"""Self-contained HTML race report (one file: data, CSS and JS inline; works offline, shareable).

    ams2season report recordings/<race folder>       or    ams2season report --latest
"""
from __future__ import annotations

import html
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from .race import COUNTED, RaceAnalysis, fmt_time

HUMAN_COLORS = ["#E4572E", "#2E86DE", "#E0A100", "#13A3A3", "#D6336C", "#A0522D", "#3F51B5", "#6D7F2A"]


def _clean(o, digits=4):
    """JSON-safe scalars; digits=None preserves precision for editable physics."""
    if isinstance(o, dict):
        return {str(k): _clean(v, digits) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v, digits) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else (f if digits is None else round(f, digits))
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def _ordinal(n) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _summary(ra: RaceAnalysis) -> list[str]:
    cls, st = ra.classification, ra.stats.set_index("name")
    if not len(cls):
        return []
    w = cls.iloc[0]
    start = "from pole" if w.grid == 1 else (f"from {_ordinal(w.grid)} on the grid" if w.grid == w.grid else "")
    out = []
    if len(cls) > 1 and cls.iloc[1].status == "finished" and cls.iloc[1].laps_down == 0:
        out.append(f"{w['name']} won {start}, {cls.iloc[1].gap:.3f}s ahead of {cls.iloc[1]['name']}.".replace("  ", " "))
    else:
        out.append(f"{w['name']} won {start}.".replace(" .", "."))
    hum = st[~st.is_ai]
    if len(hum) and st.loc[w["name"], "is_ai"]:
        top = hum.sort_values("finish").iloc[0]
        out.append(f"{top.name} was the first of you home, in {_ordinal(top.finish)}.")
    climbers = hum.dropna(subset=["positions_gained"]).sort_values("positions_gained", ascending=False)
    if len(climbers) and climbers.positions_gained.iat[0] >= 3:
        c = climbers.iloc[0]
        out.append(f"{c.name} climbed {int(c.positions_gained)} places from {_ordinal(c.grid)}.")
    return out


def _track(ra: RaceAnalysis, track_samples=None, track_width=None) -> dict:
    """Racing line from one clean lap of a well-behaved finisher, plus corner and pass positions."""
    fr, laps = ra.session.frames, ra.laps
    clean = laps[laps.clean]
    if not len(clean):
        return {"points": [], "corners": []}
    name = clean.groupby("name").size().idxmax()
    lp = clean[clean.name == name].iloc[min(1, (clean.name == name).sum() - 1)]
    prev = laps[(laps.name == name) & (laps.lap == lp.lap - 1)]
    t0 = float(prev.t_end.iat[0]) if len(prev) else float(lp.t_end - lp.time)
    seg = fr[(fr.name == name) & (fr.t >= t0) & (fr.t <= float(lp.t_end))]
    step = max(1, len(seg) // 600)
    pts = seg.iloc[::step]
    corners = []
    for c in ra.corners:
        i = int(np.argmin(np.abs(seg.lap_dist.to_numpy() - c["apex"]))) if len(seg) else None
        if i is not None:
            corners.append({"name": c["name"], "x": float(seg.x.iat[i]), "z": float(seg.z.iat[i]),
                            "kph": c.get("apex_kph")})
    from .trackmap import recording_edge_samples, track_geometry
    normal = {(r.name, int(r.lap) - 1) for r in laps[laps.clean].itertuples()}
    own = recording_edge_samples(ra.session)
    geo = track_geometry(ra.frames if ra.frames is not None else fr, seg.lap_dist.to_numpy(float), seg.x.to_numpy(float),
                         seg.z.to_numpy(float), ra.session.L, normal=normal, samples=track_samples, width=track_width,
                         extra_samples=own if own is not None and len(own) else None) if len(seg) > 20 else {}
    return {"points": [[float(x), float(z)] for x, z in zip(pts.x, pts.z)], "corners": corners, **geo}


def race_awards(ra, pinned=None):
    from .awards import race_awards as _ra
    return _ra(ra, pinned)


def _car_rows(ra: RaceAnalysis) -> list[dict]:
    from .metrics import car_stats
    try:
        return car_stats(ra.stats, ra.entrants, getattr(ra, "corner_speeds", None))
    except Exception:
        return []


def _car_extra(ra: RaceAnalysis) -> dict:
    from .metrics import corner_types, field_row
    try:
        return {"field": field_row(ra.stats), "turns": corner_types(getattr(ra, "corner_speeds", None), ra.corners)}
    except Exception:
        return {"field": None, "turns": []}


def report_data(ra: RaceAnalysis, colors: dict | None = None, top_n: int = 6, pinned: list | None = None,
                embedded: bool = False, track_samples=None, track_width=None) -> dict:
    """`colors` maps in-game name -> colour (the app passes roster-order colours so a driver keeps
    the same colour across every race); otherwise humans are coloured in finishing order."""
    sess, m = ra.session, ra.session.meta
    cls, st = ra.classification, ra.stats.set_index("name")
    humans = [n for n in cls.name if not st.loc[n, "is_ai"]]
    color = {n: HUMAN_COLORS[i % len(HUMAN_COLORS)] for i, n in enumerate(humans)}
    if colors:
        color.update({n: c for n, c in colors.items() if n in color})

    drivers = []
    for r in cls.itertuples():
        s = st.loc[r.name]
        if r.pos == 1:
            res = fmt_time(r.total_time)
        elif r.status == "finished" and r.laps_down == 0:
            res = f"+{r.gap:.3f}"
        elif r.status == "finished":
            res = f"+{int(r.laps_down)} lap{'s' if r.laps_down > 1 else ''}"
        else:
            res = {"dnf": "Retired", "dsq": "Disqualified", "disconnected": "Left", "running": "Running"}[r.status]
        d = {"name": r.name, "car": r.car, "is_ai": bool(s.is_ai), "color": color.get(r.name),
             "livery": ra.session.meta.get('_livery_appearance', {}).get(r.name),
             "pos": r.pos, "grid": r.grid, "status": r.status, "laps": r.laps, "result": res}
        for k in ("positions_gained", "lap1_gain", "best_lap", "median_clean", "consistency_s", "passes_made",
                  "passes_clean", "passes_gifted", "passes_contact", "passed_by", "passes_on_humans",
                  "battles", "battles_won", "laps_led", "pit_stops", "field_pct", "ai_rel_pace",
                  "human_rank", "top_speed_kph", "invalid_laps", "contacts", "brake_point_sd", "brake_consistency",
                  "throttle_point_sd", "throttle_consistency", "throttle_rating_source", "track_usage", "apex_gap_m", "exit_gap_m", "track_edge_source",
                  "apex_delta_slow", "apex_delta_medium", "apex_delta_fast", "s1_delta", "s2_delta", "s3_delta", "racing_share",
                  "brake_consistency_equal", "brake_consistency_reduced", "brake_consistency_excluded",
                  "throttle_consistency_equal", "throttle_consistency_reduced", "throttle_consistency_excluded"):
            d[k] = s[k] if k in s.index else None
        drivers.append(d)

    laps = {}
    for name, g in ra.laps.groupby("name"):
        laps[name] = [{"lap": x.lap, "time": x.time, "s1": x.s1, "s2": x.s2, "s3": x.s3, "valid": bool(x.valid),
                       "pit": bool(x.pit), "pos": x.position, "gap": x.gap_to_leader} for x in g.itertuples()]

    fr = sess.frames
    idx = {n: g for n, g in fr.groupby("name")}
    passes = []
    for p in ra.passes[ra.passes.kind.isin(COUNTED)].itertuples():
        g = idx.get(p.passer)
        x = z = None
        if g is not None and len(g):
            i = min(int(np.searchsorted(g.t.to_numpy(), p.t)), len(g) - 1)
            x, z = float(g.x.iat[i]), float(g.z.iat[i])
        passes.append({"t": p.t, "lap": p.lap, "corner": p.corner, "passer": p.passer, "passed": p.passed,
                       "kind": p.kind, "lap1": bool(p.lap1), "x": x, "z": z})

    started = m.get("started_at", "")
    try:
        dt = datetime.fromisoformat(started)
        date = f"{dt.day} {dt.strftime('%B %Y')}"  # no %-d: not supported on Windows
    except ValueError:
        date = started[:10]
    n_ai = int(ra.entrants.is_ai.sum())
    return _clean({
        "meta": {"track": m.get("track_location_translated") or m.get("track_location"),
                 "layout": m.get("track_variation_translated") or m.get("track_variation"),
                 "date": date, "laps": int(cls.laps.max()) if len(cls) else 0, "field": len(cls),
                 "humans": len(cls) - n_ai, "ai": n_ai, "recorded_by": m.get("label") or m.get("hostname"),
                 "folder": sess.path.name, "warnings": ra.warnings,
                 "out_of_range": sorted((m.get("out_of_range") or {}).keys())},
        "summary": _summary(ra),
        "awards": race_awards(ra, pinned),
        "top_n": int(top_n),
        "embedded": bool(embedded),
        "drivers": drivers,
        "laps": laps,
        "passes": passes,
        "battles": ra.battles.to_dict("records"),
        "pits": ra.pits.to_dict("records"),
        "corners": ra.corners,
        "track": _track(ra, track_samples, track_width),
        "racing_mode": getattr(ra, "racing_mode", "reduced"),
        "cars": _car_rows(ra),
        "car_extra": _car_extra(ra),
    })


def race_report_html(ra: RaceAnalysis, colors: dict | None = None, top_n: int = 6, pinned: list | None = None,
                     embedded: bool = False, track_samples=None, track_width=None) -> str:
    data = report_data(ra, colors, top_n=top_n, pinned=pinned, embedded=embedded, track_samples=track_samples, track_width=track_width)
    title = f"{data['meta']['track']} {data['meta']['layout']} - race report"
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload)


def render_race_report(ra: RaceAnalysis, out_path: str | Path, top_n: int = 6, pinned: list | None = None) -> Path:
    out = Path(out_path)
    out.write_text(race_report_html(ra, top_n=top_n, pinned=pinned), encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --paper:#F5F6F8; --panel:#FFFFFF; --ink:#1C2230; --muted:#5A6373; --faint:#8A93A3; --line:#DFE3E9;
  --track:#CBD1DA; --ai:#A9B0BB; --purple:#7B2CBF; --green:#178A4C; --amber:#B97A00; --red:#C81E2B;
  --row:#EEF1F5; --focus:#2E86DE; --on-purple:#FFFFFF;
  --cond:"Barlow Condensed","Roboto Condensed","Arial Narrow",system-ui,sans-serif;
  --sans:"Barlow","Segoe UI",Roboto,system-ui,sans-serif;
  box-sizing:border-box;
  padding-top:env(safe-area-inset-top,0px); padding-bottom:env(safe-area-inset-bottom,0px);
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --paper:#151A21; --panel:#1C222B; --ink:#E8EBF0; --muted:#A1A9B6; --faint:#77808F; --line:#2C333F;
  --track:#3A4350; --ai:#5E6676; --purple:#B385EA; --green:#45C784; --amber:#E2AE45; --red:#F2626B;
  --row:#222A35; --focus:#5AA4F0; --on-purple:#1A1226;
}}
:root[data-theme="dark"]{
  --paper:#151A21; --panel:#1C222B; --ink:#E8EBF0; --muted:#A1A9B6; --faint:#77808F; --line:#2C333F;
  --track:#3A4350; --ai:#5E6676; --purple:#B385EA; --green:#45C784; --amber:#E2AE45; --red:#F2626B;
  --row:#222A35; --focus:#5AA4F0; --on-purple:#1A1226;
}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
*,*::before,*::after{box-sizing:inherit}
[hidden]{display:none !important}
body{margin:0;background:var(--paper);color:var(--ink);font:400 16px/1.5 var(--sans);
  font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
main{max-width:1180px;margin:0 auto;padding:0 clamp(16px,4vw,40px) 64px}
header{padding:clamp(28px,6vw,64px) 0 8px;display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:clamp(24px,5vw,64px);align-items:start}
header h1{margin-top:0}
header .points > h2{margin-top:.35em}
@media (max-width:900px){header{grid-template-columns:minmax(0,1fr)}}
.points h2{font-size:1.25rem;margin-bottom:8px}
h1{font:600 clamp(2.6rem,8vw,5.4rem)/.92 var(--cond);letter-spacing:-.01em;margin:0}
h1 .layout{display:block;font-weight:500;color:var(--muted);font-size:.42em;letter-spacing:0;margin-top:.35em}
.sub{color:var(--muted);margin:14px 0 0;max-width:70ch}
.summary{font:500 clamp(1.15rem,2.2vw,1.45rem)/1.4 var(--sans);margin:26px 0 0;max-width:62ch}
h2{font:600 1.7rem/1.1 var(--cond);margin:0 0 4px;letter-spacing:.005em}
.explain{color:var(--muted);margin:0 0 16px;font-size:.95rem;max-width:72ch}
section{margin-top:clamp(40px,6vw,64px)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:clamp(12px,2vw,20px)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.cols{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:clamp(24px,4vw,48px);align-items:start}
@media (max-width:900px){.cols{grid-template-columns:minmax(0,1fr)}}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}
.chip{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);background:var(--panel);
  color:var(--ink);font:500 .95rem/1 var(--sans);padding:8px 12px;border-radius:999px;cursor:pointer}
.chip i{width:12px;height:12px;border-radius:50%;display:inline-block}
.chip[aria-pressed="true"]{border-color:var(--ink);box-shadow:inset 0 0 0 1px var(--ink)}
.chip.clear{color:var(--muted)}
button:focus-visible,tr:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
svg text{font-family:var(--sans);fill:var(--ink)}
svg .muted{fill:var(--muted)} svg .faint{fill:var(--faint)}
.series{transition:opacity .18s ease}
.dim .series{opacity:.12} .dim .series.on{opacity:1}
table{border-collapse:collapse;width:100%;font-size:.95rem}
th{font:600 .82rem/1.2 var(--sans);color:var(--muted);text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td.num,th.num{text-align:right}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--row)}
tr.on{background:var(--row)}
tr.on td:first-child{box-shadow:inset 3px 0 0 var(--ink)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;vertical-align:middle}
.ai-name{color:var(--muted)}
.pos{font:600 1.05rem/1 var(--cond)}
.up{color:var(--green)} .down{color:var(--red)}
ul.hl{list-style:none;margin:0;padding:0}
ul.hl li b{font-weight:600;margin-right:6px}
ul.hl li .d{color:var(--muted)}
.more{background:none;border:0;padding:10px 0 0;color:var(--ink);text-decoration:underline;cursor:pointer;font:500 .95rem var(--sans)}
.watch{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:3px 10px;
  font:500 .8rem var(--sans);cursor:pointer;margin-left:8px;vertical-align:1px}
.watch:hover{border-color:var(--ink)}
.awgroup{margin-top:22px}
.awgroup h3{font:600 1.15rem/1.2 var(--cond);margin:0 0 4px;color:var(--muted)}
.aw{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 16px;padding:11px 0;border-bottom:1px solid var(--line);align-items:baseline}
.aw .tt{font-weight:600}
.aw .vv{font:600 1.05rem/1 var(--cond);text-align:right;white-space:nowrap}
.aw .dd{color:var(--muted);grid-column:1/-1}
.awcols{column-width:340px;column-gap:48px}
.awcols .awgroup{break-inside:avoid}
#pits-wrap{margin-top:clamp(32px,5vw,48px)}
.mapmodes{display:inline-flex;gap:6px;margin-left:auto;margin-right:8px}
.mapmodes .chip[aria-pressed="true"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.sbar{display:inline-block;width:56px;height:7px;border-radius:4px;background:var(--line);overflow:hidden;margin-right:8px;vertical-align:middle}
.sbar i{display:block;height:100%}
tr.ai td{color:var(--muted)}
tr.fieldrow td{font-style:italic;background:var(--paper);border-bottom:2px solid var(--line)}
td.bestcell{background:var(--green);color:#fff;font-weight:600;border-radius:4px}
table.compact th{white-space:normal;font-size:.74rem;line-height:1.2;vertical-align:bottom}
.tag{margin-left:8px;font-size:.72rem;font-weight:600;padding:1px 8px;border-radius:999px;background:var(--green);color:#fff}
td.gain{color:var(--green)} td.lose{color:var(--red)}
thead th{cursor:pointer;user-select:none}
th[data-sort="asc"]::after{content:" \25B2";font-size:.7em}
th[data-sort="desc"]::after{content:" \25BC";font-size:.7em}
.stylemodes{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:6px 0 10px}
.stylemodes .chip[aria-pressed="true"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.pagelink{font-size:.75rem;color:var(--muted);text-decoration:underline;grid-column:1/-1}
.heatbar{display:inline-block;width:160px;height:10px;border-radius:5px;background:linear-gradient(90deg,rgb(253,230,138),rgb(251,146,60),rgb(220,38,38),rgb(127,29,29))}
ul.hl li{padding:10px 0;border-bottom:1px solid var(--line);font-size:.97rem}
ul.hl li:first-child{padding-top:0}
.laps td{padding:6px 8px;font-size:.9rem}
.laps td.fast{color:var(--on-purple);background:var(--purple);border-radius:4px;font-weight:600}
.laps td.pb{color:var(--green);font-weight:600}
.laps td.inv{color:var(--faint);text-decoration:line-through}
.laps td.pit::after{content:"pit";font-size:.7rem;color:var(--amber);margin-left:4px;font-weight:600}
.key{display:flex;flex-wrap:wrap;gap:18px;color:var(--muted);font-size:.88rem;margin-top:12px}
.key span{display:inline-flex;align-items:center;gap:6px}
.sw{width:14px;height:14px;border-radius:3px;display:inline-block}
.kind{font-size:.82rem;font-weight:600}
#passlog td{white-space:normal;padding:7px 8px}
#passlog{width:100%}
#passlog td{white-space:normal;overflow-wrap:anywhere}
#passlog td:first-child,#passlog td:nth-child(2),#passlog td:last-child{white-space:nowrap}
#passlog th,#passlog td{padding:7px 8px}
.k-clean{color:var(--ink)} .k-gifted{color:var(--amber)} .k-contact{color:var(--red)}
.mapbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.note{color:var(--muted);font-size:.85rem;margin-top:24px}
footer{color:var(--faint);font-size:.85rem;margin-top:56px;border-top:1px solid var(--line);padding-top:16px}
@media (prefers-reduced-motion:reduce){.series{transition:none}}
.fsable{position:relative}
.fsbtn{position:absolute;top:8px;right:8px;z-index:2;border:1px solid var(--line);background:var(--panel);color:var(--ink);
  border-radius:7px;padding:4px 10px;font:500 .8rem var(--sans);cursor:pointer;opacity:.85}
.fsbtn:hover{opacity:1;border-color:var(--ink)}
.fsable:fullscreen{background:var(--paper);padding:28px;display:flex;flex-direction:column;justify-content:center;overflow:auto}
.fsable:fullscreen svg{width:100% !important;height:calc(100vh - 90px) !important;min-width:0 !important;max-height:none !important}
</style>
</head>
<body>
<main>
  <header>
    <div>
      <h1 id="title"></h1>
      <p class="sub" id="sub"></p>
      <p class="summary" id="summary"></p>
    </div>
    <div class="points">
      <h2>Talking points</h2>
      <ul class="hl" id="highlights"></ul>
    </div>
  </header>

  <section aria-labelledby="h-unfold">
    <h2 id="h-unfold">How it unfolded</h2>
    <p class="explain">Running position at the end of every lap, starting from the grid. Pick a driver to follow them through this whole page.</p>
    <div class="chips" id="chips"></div>
    <div class="panel scroll"><svg id="lapchart" role="img" aria-label="Position by lap chart"></svg></div>
  </section>

  <section>
    <h2>Classification</h2>
    <p class="explain">Passes are on-track moves made / conceded. Pit-stop shuffles don't count. Click a row to follow that driver.</p>
    <div class="panel scroll"><table id="results"></table></div>
  </section>

  <section>
    <h2>Gap to the leader</h2>
    <p class="explain">Seconds behind whoever was leading at each lap line. Flat lines are a car holding pace; a cliff is a pit stop, spin or off.</p>
    <div class="panel scroll"><svg id="gapchart" role="img" aria-label="Gap to leader by lap"></svg></div>
  </section>



  <section>
    <h2>Lap times</h2>
    <p class="explain">Purple is the fastest lap of the race, green is a driver's personal best, struck through means the lap was invalidated. Hover a time for sector splits.</p>
    <div class="panel scroll"><table class="laps" id="laptimes"></table></div>
  </section>

  <section id="humans-sec">
    <h2>Just the humans</h2>
    <p class="explain">"vs AI" compares your median clean lap with the AI's median: below 1.000 is quicker than the AI. "Field" is the share of the grid you finished ahead of.</p>
    <div class="panel scroll"><table id="humans"></table></div>
  </section>

  <!-- driving style lives on its own page now (Driving style in the race review) -->



  <section id="awards-sec" hidden>
    <h2>Every award</h2>
    <p class="explain">Everything this race's data has to say, grouped. The most interesting ones are also at the top of the page.</p>
    <div class="awcols" id="allawards"></div>
  </section>

  <section id="extras">
    <div id="battles-wrap">
      <h2>Battles</h2>
      <p class="explain">Cars running nose-to-tail, within a second, for at least two laps.</p>
      <div class="panel scroll"><table id="battles"></table></div>
    </div>
    <div id="pits-wrap">
      <h2>Pit stops</h2>
      <p class="explain">Time from pit entry to pit exit, and time stationary.</p>
      <div class="panel scroll"><table id="pits"></table></div>
    </div>
  </section>

  <div class="note" id="notes"></div>
  <footer id="footer"></footer>
</main>

<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
var D = JSON.parse(document.getElementById("data").textContent);
var NS = "http://www.w3.org/2000/svg";
var byName = {}; D.drivers.forEach(function(d){ byName[d.name] = d; });
var focus = null;

function $(id){ return document.getElementById(id); }
function el(tag, attrs, text){ var e = document.createElement(tag); setA(e, attrs); if (text != null) e.textContent = text; return e; }
function sv(tag, attrs, text){ var e = document.createElementNS(NS, tag); setA(e, attrs); if (text != null) e.textContent = text; return e; }
function setA(e, a){ if (a) for (var k in a) if (a[k] != null) e.setAttribute(k, a[k]); }
function colorOf(n){ var d = byName[n]; return d && d.color ? d.color : "var(--ai)"; }
function isHuman(n){ var d = byName[n]; return d && !d.is_ai; }
function t(x){ if (x == null) return "-"; var m = Math.floor(x/60), s = x - m*60; return m ? m + ":" + (s < 10 ? "0" : "") + s.toFixed(3) : s.toFixed(3); }
function f(x, d){ return x == null ? "-" : Number(x).toFixed(d); }
function signed(x){ return x == null ? "-" : (x > 0 ? "+" : "") + Math.round(x); }

// ---------------------------------------------------------------- header
var M = D.meta;
$("title").textContent = M.track;
$("title").appendChild(el("span", {"class": "layout"}, M.layout));
$("sub").textContent = M.date + ". " + M.laps + " laps, " + M.field + " cars: " + M.humans +
  (M.humans === 1 ? " human" : " humans") + " and " + M.ai + " AI.";
$("summary").textContent = D.summary.join(" ");

// ---------------------------------------------------------------- focus handling
function setFocus(name){
  focus = (focus === name) ? null : name;
  ["lapchart", "gapchart"].forEach(function(id){ $(id).classList.toggle("dim", !!focus); });
  document.querySelectorAll(".series").forEach(function(s){ s.classList.toggle("on", s.dataset.name === focus); });
  document.querySelectorAll("tr[data-name]").forEach(function(r){ r.classList.toggle("on", r.dataset.name === focus); });
  document.querySelectorAll(".chip[data-name]").forEach(function(c){ c.setAttribute("aria-pressed", c.dataset.name === focus); });
  $("clearchip").hidden = !focus;
  drawMap(); drawPassLog(); drawStyle();
}
function rowFocus(tr, name){
  tr.dataset.name = name; tr.tabIndex = 0;
  tr.addEventListener("click", function(){ setFocus(name); });
  tr.addEventListener("keydown", function(e){ if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setFocus(name); } });
}

// ---------------------------------------------------------------- chips
var chips = $("chips");
D.drivers.filter(function(d){ return !d.is_ai; }).forEach(function(d){
  var b = el("button", {"class": "chip", "data-name": d.name, "aria-pressed": "false"});
  var i = el("i"); i.style.background = d.color; b.appendChild(i); b.appendChild(document.createTextNode(d.name));
  b.addEventListener("click", function(){ setFocus(d.name); });
  chips.appendChild(b);
});
var clr = el("button", {"class": "chip clear", id: "clearchip"}, "Show everyone"); clr.hidden = true;
clr.addEventListener("click", function(){ setFocus(focus); });
chips.appendChild(clr);

// ---------------------------------------------------------------- lap chart
(function lapChart(){
  var svg = $("lapchart"), N = D.drivers.length, L = M.laps;
  var rowH = Math.max(20, Math.min(30, 560 / Math.max(N, 1)));
  var left = 168, right = 190, top = 14, bottom = 34, W = 1000, H = top + bottom + rowH * Math.max(N - 1, 1);
  setA(svg, {viewBox: "0 0 " + W + " " + H, width: "100%", style: "min-width:760px;display:block"});
  var x = function(l){ return left + l * (W - left - right) / Math.max(L, 1); };
  var y = function(p){ return top + (p - 1) * rowH; };
  for (var l = 0; l <= L; l++) {
    svg.appendChild(sv("line", {x1: x(l), x2: x(l), y1: top - 6, y2: H - bottom + 6, stroke: "var(--line)", "stroke-width": 1}));
    svg.appendChild(sv("text", {x: x(l), y: H - 10, "text-anchor": "middle", "font-size": 12, "class": "faint"}, l === 0 ? "Grid" : "L" + l));
  }
  var order = D.drivers.slice().sort(function(a, b){ return (a.is_ai === b.is_ai) ? 0 : (a.is_ai ? -1 : 1); });
  order.forEach(function(d){
    var laps = (D.laps[d.name] || []).filter(function(p){ return p.pos != null; });
    var pts = [];
    if (d.grid != null) pts.push([x(0), y(d.grid)]);
    laps.forEach(function(p){ pts.push([x(p.lap), y(p.pos)]); });
    var g = sv("g", {"class": "series", "data-name": d.name});
    g.appendChild(sv("title", null, d.name + (d.is_ai ? " (AI)" : "") + ": P" + d.grid + " to P" + d.pos));
    if (pts.length > 1) g.appendChild(sv("polyline", {points: pts.map(function(p){ return p.join(","); }).join(" "), fill: "none",
      stroke: colorOf(d.name), "stroke-width": d.is_ai ? 1.6 : 3.4, "stroke-linejoin": "round", "stroke-linecap": "round"}));
    var last = pts[pts.length - 1];
    if (last && !d.is_ai) g.appendChild(sv("circle", {cx: last[0], cy: last[1], r: 4.5, fill: colorOf(d.name)}));
    if (last && d.status !== "finished" && d.status !== "running")
      g.appendChild(sv("text", {x: last[0] + 8, y: last[1] + 4, "font-size": 11, "class": "faint"}, d.result));
    g.addEventListener("click", function(){ setFocus(d.name); });
    g.style.cursor = "pointer";
    svg.appendChild(g);
  });
  D.drivers.forEach(function(d){
    if (d.grid != null) svg.appendChild(sv("text", {x: left - 12, y: y(d.grid) + 4, "text-anchor": "end", "font-size": 13,
      "font-weight": d.is_ai ? 400 : 600, "class": d.is_ai ? "muted" : null}, d.name + "  " + d.grid));
    if (d.status === "finished" || d.status === "running")
      svg.appendChild(sv("text", {x: W - right + 12, y: y(d.pos) + 4, "font-size": 13, "font-weight": d.is_ai ? 400 : 600,
        "class": d.is_ai ? "muted" : null}, d.pos + "  " + d.name));
  });
})();

// ---------------------------------------------------------------- results
(function results(){
  var tb = $("results");
  var head = el("thead"), hr = el("tr");
  [["Pos",""],["Driver",""],["Car",""],["Grid","num"],["+/-","num"],["Result","num"],["Best lap","num"],["Passes","num"]]
    .forEach(function(h){ hr.appendChild(el("th", {"class": h[1]}, h[0])); });
  head.appendChild(hr); tb.appendChild(head);
  var body = el("tbody");
  D.drivers.forEach(function(d){
    var tr = el("tr"); rowFocus(tr, d.name);
    tr.appendChild(el("td", {"class": "pos"}, d.pos));
    var nm = el("td"); if (!d.is_ai) { var dot = el("span", {"class": "dot"}); dot.style.background = d.color; nm.appendChild(dot); }
    if (d.livery && d.livery.image) {
      var img = el('img', {src: d.livery.image, alt: (d.livery.car_name || d.car) + ' · ' + (d.livery.livery_name || 'Livery')});
      img.style.cssText = 'width:64px;height:36px;object-fit:contain;vertical-align:middle;margin-right:8px';
      img.addEventListener('error', function () { this.hidden = true; }); nm.appendChild(img);
    }
    nm.appendChild(el("span", {"class": d.is_ai ? "ai-name" : null}, d.name)); tr.appendChild(nm);
    tr.appendChild(el("td", {"class": "ai-name"}, d.car));
    tr.appendChild(el("td", {"class": "num"}, d.grid == null ? "-" : d.grid));
    var g = d.positions_gained; tr.appendChild(el("td", {"class": "num " + (g > 0 ? "up" : g < 0 ? "down" : "")}, signed(g)));
    tr.appendChild(el("td", {"class": "num"}, d.result));
    tr.appendChild(el("td", {"class": "num"}, t(d.best_lap)));
    tr.appendChild(el("td", {"class": "num"}, d.passes_made + " / " + d.passed_by));
    body.appendChild(tr);
  });
  tb.appendChild(body);
})();

// ---------------------------------------------------------------- awards / talking points
function watchBtn(t){
  if (!D.embedded || t == null) return null;
  var b = el("button", {"class": "watch", title: "Jump to this moment in the replay"}, "Watch");
  b.addEventListener("click", function(e){ e.stopPropagation(); parent.postMessage({type: "ams2season-replay", t: t}, location.origin); });
  return b;
}
(function awards(){
  var AW = D.awards || [], n = Math.max(1, D.top_n || 6), list = $("highlights");
  AW.slice(0, n).forEach(function(a){
    var li = el("li"); li.appendChild(el("b", null, a.title)); li.appendChild(el("span", {"class": "d"}, a.detail));
    var w = watchBtn(a.t); if (w) li.appendChild(w);
    list.appendChild(li);
  });
  if (AW.length > n) {
    var more = el("button", {"class": "more"}, "See all " + AW.length + " awards");
    more.addEventListener("click", function(){
      var sec = $("awards-sec"); sec.hidden = !sec.hidden;
      more.textContent = sec.hidden ? "See all " + AW.length + " awards" : "Hide the full list";
      if (!sec.hidden) sec.scrollIntoView({behavior: "smooth", block: "start"});
    });
    list.parentNode.appendChild(more);
  }
  var order = ["Battles", "Overtaking", "Positions", "Start", "Pace", "Consistency", "Driving style", "Errors", "Strategy", "Hard luck"];
  var qs = new URLSearchParams(location.search), recId = qs.get("recording"), champQ = qs.get("champ");
  var PAGES = {overtakes: "Overtaking", errors: "Errors", pace: "Pace", style: "Driving style", cars: "Cars"};
  var pageLink = function (a) {
    if (!recId || !PAGES[a.page]) return null;
    return el("a", {"class": "pagelink", target: "_parent", href: "/#/" + a.page + "/" + encodeURIComponent(recId) + (champQ ? "?champ=" + encodeURIComponent(champQ) : "")}, "on the " + PAGES[a.page] + " page");
  };
  var box = $("allawards");
  order.forEach(function(g){
    var items = AW.filter(function(a){ return a.group === g; });
    if (!items.length) return;
    var grp = el("div", {"class": "awgroup"}); grp.appendChild(el("h3", null, g));
    items.forEach(function(a){
      var row = el("div", {"class": "aw"});
      var tt = el("div", {"class": "tt"});
      if (a.winner && byName[a.winner] && byName[a.winner].color) { var dot = el("span", {"class": "dot"}); dot.style.background = byName[a.winner].color; tt.appendChild(dot); }
      tt.appendChild(document.createTextNode(a.title)); var w = watchBtn(a.t); if (w) tt.appendChild(w);
      row.appendChild(tt); row.appendChild(el("div", {"class": "vv"}, a.value)); row.appendChild(el("div", {"class": "dd"}, a.detail));
      var pl = pageLink(a); if (pl) row.appendChild(pl);
      grp.appendChild(row);
    });
    box.appendChild(grp);
  });
})();

// ---------------------------------------------------------------- gap chart
(function gapChart(){
  var svg = $("gapchart"), L = M.laps, W = 1000, H = 380, left = 56, right = 150, top = 16, bottom = 34;
  setA(svg, {viewBox: "0 0 " + W + " " + H, width: "100%", style: "min-width:760px;display:block"});
  var gaps = [];
  D.drivers.forEach(function(d){ (D.laps[d.name] || []).forEach(function(p){ if (p.gap != null) gaps.push(p.gap); }); });
  gaps.sort(function(a, b){ return a - b; });
  var cap = gaps.length ? Math.max(5, gaps[Math.floor(gaps.length * 0.9)] * 1.25) : 10;
  var step = cap > 60 ? 15 : cap > 30 ? 10 : cap > 12 ? 5 : cap > 6 ? 2 : 1;
  var x = function(l){ return left + (l - 1) * (W - left - right) / Math.max(L - 1, 1); };
  var y = function(g){ return top + Math.min(g, cap) / cap * (H - top - bottom); };
  for (var s = 0; s <= cap; s += step) {
    svg.appendChild(sv("line", {x1: left, x2: W - right, y1: y(s), y2: y(s), stroke: "var(--line)", "stroke-width": 1}));
    svg.appendChild(sv("text", {x: left - 10, y: y(s) + 4, "text-anchor": "end", "font-size": 12, "class": "faint"}, s === 0 ? "Leader" : "+" + s + "s"));
  }
  for (var l = 1; l <= L; l++) svg.appendChild(sv("text", {x: x(l), y: H - 10, "text-anchor": "middle", "font-size": 12, "class": "faint"}, "L" + l));
  var order = D.drivers.slice().sort(function(a, b){ return (a.is_ai === b.is_ai) ? 0 : (a.is_ai ? -1 : 1); });
  order.forEach(function(d){
    var laps = (D.laps[d.name] || []).filter(function(p){ return p.gap != null; });
    if (!laps.length) return;
    var g = sv("g", {"class": "series", "data-name": d.name});
    g.appendChild(sv("title", null, d.name));
    var pts = laps.map(function(p){ return x(p.lap) + "," + y(p.gap); }).join(" ");
    if (laps.length > 1) g.appendChild(sv("polyline", {points: pts, fill: "none", stroke: colorOf(d.name),
      "stroke-width": d.is_ai ? 1.5 : 3, "stroke-linejoin": "round"}));
    var last = laps[laps.length - 1];
    if (!d.is_ai) {
      g.appendChild(sv("circle", {cx: x(last.lap), cy: y(last.gap), r: 4, fill: colorOf(d.name)}));
      if (last.lap === L) g.appendChild(sv("text", {x: W - right + 10, y: y(last.gap) + 4, "font-size": 13, "font-weight": 600},
        d.name + (last.gap > cap ? " (+" + Math.round(last.gap) + "s)" : "")));
    }
    g.addEventListener("click", function(){ setFocus(d.name); }); g.style.cursor = "pointer";
    svg.appendChild(g);
  });
})();

// ---------------------------------------------------------------- track map
var flip = false;
try { flip = localStorage.getItem("ams2season-flip-" + M.track + M.layout) === "1"; } catch (e) {}
$("flip") && $("flip").addEventListener("click", function(){
  flip = !flip;
  try { localStorage.setItem("ams2season-flip-" + M.track + M.layout, flip ? "1" : "0"); } catch (e) {}
  drawMap();
});
function drawMap(){
  if (!$("map")) return;  // the pass map lives on the Overtaking page now
  var svg = $("map"); while (svg.firstChild) svg.removeChild(svg.firstChild);
  var P = D.track.points;
  if (!P.length) { svg.appendChild(sv("text", {x: 10, y: 20}, "No clean lap to draw the track from.")); return; }
  var X = function(p){ return p[0]; }, Z = function(p){ return flip ? p[1] : -p[1]; };
  var xs = P.map(X), zs = P.map(Z);
  var minx = Math.min.apply(null, xs), maxx = Math.max.apply(null, xs), minz = Math.min.apply(null, zs), maxz = Math.max.apply(null, zs);
  var pad = Math.max(maxx - minx, maxz - minz) * 0.08 + 20;
  setA(svg, {viewBox: (minx - pad) + " " + (minz - pad) + " " + (maxx - minx + 2 * pad) + " " + (maxz - minz + 2 * pad), width: "100%",
    style: "display:block;max-height:560px"});
  var span = Math.max(maxx - minx, maxz - minz), u = span / 500;
  svg.appendChild(sv("polyline", {points: P.map(function(p){ return X(p) + "," + Z(p); }).join(" ") + " " + X(P[0]) + "," + Z(P[0]),
    fill: "none", stroke: "var(--track)", "stroke-width": 11 * u, "stroke-linejoin": "round", "stroke-linecap": "round"}));
  var cx = (minx + maxx) / 2, cz = (minz + maxz) / 2;
  var counted = D.passes.filter(function(p){ return p.x != null; });
  var shown = focus ? counted.filter(function(p){ return p.passer === focus || p.passed === focus; }) : counted;
  $("heatkey").hidden = mapMode !== "heat"; $("dotkey").hidden = mapMode === "heat";
  if (mapMode === "heat") { drawHeat(svg, P, X, Z, u, shown); drawBadges(svg, cx, cz, u); return; }
  drawBadges(svg, cx, cz, u);
  var col = {clean: "var(--ink)", gifted: "var(--amber)", contact: "var(--red)"};
  shown.forEach(function(p){
    var made = !focus || p.passer === focus;
    var c = sv("circle", {cx: p.x, cy: flip ? p.z : -p.z, r: 6 * u, fill: made ? col[p.kind] : "none",
      stroke: col[p.kind], "stroke-width": made ? 1.5 * u : 2.5 * u, "fill-opacity": made ? 0.85 : 0});
    c.appendChild(sv("title", null, "Lap " + p.lap + (p.corner ? ", " + p.corner : "") + ": " + p.passer + " passed " + p.passed + " (" + p.kind + ")"));
    svg.appendChild(c);
  });
  $("ringkey").hidden = !focus;
  var made = focus ? shown.filter(function(p){ return p.passer === focus; }).length : 0;
  $("mapexplain").textContent = focus ? focus + ": " + made + " passes made (filled), " + (shown.length - made) + " conceded (rings)."
    : "Every counted pass, plotted where it happened. Turns are numbered from the start line, found from the track's shape.";
}
function drawBadges(svg, cx, cz, u){  // numbered turn badges tied to their apexes; fixed colours so no theme can hide them
  D.track.corners.forEach(function(c){
    var px = c.x, pz = flip ? c.z : -c.z, dx = px - cx, dz = pz - cz, len = Math.hypot(dx, dz) || 1;
    var bx = px + dx / len * 30 * u, bz = pz + dz / len * 30 * u;
    svg.appendChild(sv("line", {x1: px, y1: pz, x2: bx, y2: bz, style: "stroke:#8A93A3", "stroke-width": 1.4 * u}));
    svg.appendChild(sv("rect", {x: bx - 15 * u, y: bz - 9 * u, width: 30 * u, height: 18 * u, rx: 9 * u,
      style: "fill:#1C2230;stroke:#8A93A3", "stroke-width": 0.8 * u}));
    svg.appendChild(sv("text", {x: bx, y: bz + 4.5 * u, "text-anchor": "middle", "font-size": 12.5 * u, "font-weight": 700,
      style: "fill:#FFFFFF"}, c.name));
  });
}
var HEAT = [[253, 230, 138], [251, 146, 60], [220, 38, 38], [127, 29, 29]];  // pale yellow, orange, red, deep red
function cssRGB(name, fallback){
  var probe = document.createElement("span"); probe.style.color = "var(" + name + ")"; document.body.appendChild(probe);
  var m = getComputedStyle(probe).color.match(/\d+/g); probe.remove();
  return m ? m.slice(0, 3).map(Number) : fallback;
}
function heatColor(v, base){  // from the track's own colour at zero, through yellow and orange to deep red
  var stops = [base].concat(HEAT), x = Math.max(0, Math.min(1, v)) * (stops.length - 1);
  var i = Math.min(stops.length - 2, Math.floor(x)), f = x - i;
  return "rgb(" + stops[i].map(function(a, k){ return Math.round(a + (stops[i + 1][k] - a) * f); }).join(",") + ")";
}
function drawHeat(svg, P, X, Z, u, passes){
  // Pass density along the track: each pass spreads over ~45 m either side, so busy stretches glow
  var n = P.length, dens = new Array(n).fill(0), sig = 45, near = new Array(passes.length);
  passes.forEach(function(p, j){
    var best = 0, bd = Infinity;
    for (var i = 0; i < n; i++) { var d = (P[i][0] - p.x) * (P[i][0] - p.x) + (P[i][1] - p.z) * (P[i][1] - p.z); if (d < bd) { bd = d; best = i; } }
    near[j] = best;
  });
  var cum = [0];  // distance along the outline, to spread each pass along the track rather than through the infield
  for (var i = 1; i < n; i++) cum.push(cum[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));
  var Ltot = cum[n - 1] + Math.hypot(P[0][0] - P[n - 1][0], P[0][1] - P[n - 1][1]);
  near.forEach(function(k){
    for (var i = 0; i < n; i++) { var d = Math.abs(cum[i] - cum[k]); d = Math.min(d, Ltot - d); if (d < 3 * sig) dens[i] += Math.exp(-d * d / (2 * sig * sig)); }
  });
  var mx = Math.max.apply(null, dens) || 1, base = cssRGB("--track", [203, 209, 218]);
  for (i = 0; i < n; i++) {  // opaque segments, so overlapping joins don't bead
    var j = (i + 1) % n, v = Math.sqrt(dens[i] / mx);
    if (v < 0.05) continue;
    svg.appendChild(sv("line", {x1: X(P[i]), y1: Z(P[i]), x2: X(P[j]), y2: Z(P[j]), stroke: heatColor(v, base),
      "stroke-width": (8 + 6 * v) * u, "stroke-linecap": "round"}));
  }
  // label the busiest stretches with their pass count
  var peaks = [];
  for (i = 0; i < n; i++) {
    var v2 = dens[i]; if (v2 / mx < 0.35) continue;
    var isPeak = true;
    for (var d2 = -12; d2 <= 12 && isPeak; d2++) if (d2 && dens[(i + d2 + n) % n] > v2) isPeak = false;
    if (isPeak) peaks.push(i);
  }
  peaks.sort(function(a, b){ return dens[b] - dens[a]; });
  peaks.slice(0, 3).forEach(function(i){
    var cnt = near.filter(function(k){ var d = Math.abs(cum[k] - cum[i]); return Math.min(d, Ltot - d) < 90; }).length;
    var cx0 = (Math.min.apply(null, P.map(X)) + Math.max.apply(null, P.map(X))) / 2, cz0 = (Math.min.apply(null, P.map(Z)) + Math.max.apply(null, P.map(Z))) / 2;
    var dx = cx0 - X(P[i]), dz = cz0 - Z(P[i]), dl = Math.hypot(dx, dz) || 1;  // inside the track (badges sit outside)
    var t = sv("text", {x: X(P[i]) + dx / dl * 26 * u, y: Z(P[i]) + dz / dl * 26 * u + 4 * u, "font-size": 13 * u, "font-weight": 700, "text-anchor": "middle",
      style: "fill:var(--ink);paint-order:stroke;stroke:var(--paper);stroke-width:" + (4 * u) + "px"}, cnt + " pass" + (cnt === 1 ? "" : "es"));
    svg.appendChild(t);
  });
  $("mapexplain").textContent = (focus ? focus + "'s passes, made and conceded: " : "Where passes happened: ") +
    "the hotter the colour, the more passes on that stretch. " + passes.length + " pass" + (passes.length === 1 ? "" : "es") + " in all.";
}
var mapMode = "heat";
["heat", "dots"].forEach(function(m){
  if ($("mode-" + m)) $("mode-" + m).addEventListener("click", function(){
    mapMode = m;
    ["heat", "dots"].forEach(function(k){ $("mode-" + k).setAttribute("aria-pressed", String(k === m)); });
    drawMap();
  });
});
drawMap();

// ---------------------------------------------------------------- driving style and cars
function swatch(d){  // the driver's colour dot (humans only), as in the other tables
  var dot = el("span", {"class": "dot"});
  if (!d.is_ai && d.color) dot.style.background = d.color; else dot.style.visibility = "hidden";
  return dot;
}
function scoreCell(v, sd){
  if (v == null || v !== v) return el("td", {"class": "num muted"}, "-");
  var td = el("td", {"class": "num"});
  var bar = el("span", {"class": "sbar"}); var fillb = el("i"); fillb.style.width = Math.max(0, Math.min(100, v)) + "%";
  fillb.style.background = v >= 80 ? "var(--green)" : v >= 60 ? "var(--amber)" : "var(--red)";
  bar.appendChild(fillb); td.appendChild(bar);
  td.appendChild(el("b", null, String(Math.round(v))));
  if (sd != null && sd === sd) td.appendChild(el("span", {"class": "muted"}, " (\u00b1" + sd.toFixed(1) + " m)"));
  return td;
}
function drawStyle(){
  if (!$("style")) return;  // moved to the Driving style page
  var tb = $("style"); while (tb.firstChild) tb.removeChild(tb.firstChild);
  var rows = D.drivers.filter(function(d){ return d.brake_consistency != null || d.track_usage != null; });
  $("style-sec").hidden = !rows.length;
  if (!rows.length) return;
  var head = el("thead"), hr = el("tr");
  ["Pos", "Driver", "Braking points", "Throttle pickup", "Track usage", "At the apex", "At exit", "Racing corners"].forEach(function(h, i){ hr.appendChild(el("th", {"class": i > 1 ? "num" : ""}, h)); });
  head.appendChild(hr); tb.appendChild(head);
  var body = el("tbody");
  rows.forEach(function(d){
    var tr = el("tr", {"class": (focus && focus !== d.name ? "dim" : "") + (d.is_ai ? " ai" : "")});
    tr.appendChild(el("td", {"class": "pos"}, String(d.pos)));
    var nm = el("td"); nm.appendChild(swatch(d)); nm.appendChild(el(d.is_ai ? "span" : "b", null, d.name)); tr.appendChild(nm);
    var bm = d["brake_consistency_" + styleMode], tm = d["throttle_consistency_" + styleMode];
    tr.appendChild(scoreCell(bm != null ? bm : d.brake_consistency, styleMode === D.racing_mode ? d.brake_point_sd : null));
    tr.appendChild(scoreCell(tm != null ? tm : d.throttle_consistency, styleMode === D.racing_mode ? d.throttle_point_sd : null));
    tr.appendChild(scoreCell(d.track_usage, null));
    tr.appendChild(el("td", {"class": "num"}, d.apex_gap_m == null || d.apex_gap_m !== d.apex_gap_m ? "-" : d.apex_gap_m.toFixed(2) + " m"));
    tr.appendChild(el("td", {"class": "num", "title": "Sustained wheel clearance to the outside edge at exit; linked-corner exits can intentionally stay narrower."}, d.exit_gap_m == null || d.exit_gap_m !== d.exit_gap_m ? "-" : d.exit_gap_m.toFixed(2) + " m"));
    tr.appendChild(el("td", {"class": "num muted"}, d.racing_share == null || d.racing_share !== d.racing_share ? "-" : Math.round(d.racing_share) + "%"));
    body.appendChild(tr);
  });
  tb.appendChild(body);
}
function drawCars(){
  var tb = $("cars"); while (tb.firstChild) tb.removeChild(tb.firstChild);
  var C = D.cars || [];
  $("cars-sec").hidden = C.length < 2;
  if (C.length < 2) return;
  var head = el("thead"), hr = el("tr");
  ["Car", "Drivers", "Pace", "vs field", "Best lap", "Top speed", "Best finish", "Avg finish", "Wins"].forEach(function(h, i){ hr.appendChild(el("th", {"class": i ? "num" : ""}, h)); });
  head.appendChild(hr); tb.appendChild(head);
  var body = el("tbody"), fastest = Math.min.apply(null, C.filter(function(c){ return c.best_lap; }).map(function(c){ return c.best_lap; }));
  var F = (D.car_extra || {}).field;
  if (F) {  // the whole field as the reference row
    var fr = el("tr", {"class": "fieldrow"});
    fr.appendChild(el("td", null, "Whole field"));
    fr.appendChild(el("td", {"class": "num"}, String(F.drivers)));
    fr.appendChild(el("td", {"class": "num"}, F.pace ? t(F.pace) : "-"));
    fr.appendChild(el("td", {"class": "num muted"}, "reference"));
    fr.appendChild(el("td", {"class": "num"}, F.best_lap ? t(F.best_lap) : "-"));
    fr.appendChild(el("td", {"class": "num"}, F.top_speed ? Math.round(F.top_speed) + " km/h" : "-"));
    ["", "", ""].forEach(function(){ fr.appendChild(el("td", {"class": "num muted"}, "")); });
    body.appendChild(fr);
  }
  C.forEach(function(c, i){
    var tr = el("tr");
    var nm = el("td"); nm.appendChild(el("b", null, c.car)); if (i === 0 && c.pace) nm.appendChild(el("span", {"class": "tag"}, "fastest")); tr.appendChild(nm);
    tr.appendChild(el("td", {"class": "num"}, c.drivers + (c.humans ? " (" + c.humans + " human" + (c.humans > 1 ? "s" : "") + ")" : "")));
    tr.appendChild(el("td", {"class": "num"}, c.pace ? t(c.pace) : "-"));
    var vs = el("td", {"class": "num " + (c.pace_vs_field < -0.05 ? "gain" : c.pace_vs_field > 0.05 ? "lose" : "")}, c.pace_vs_field == null ? "-" : (c.pace_vs_field > 0 ? "+" : "") + c.pace_vs_field.toFixed(2) + "%");
    tr.appendChild(vs);
    tr.appendChild(el("td", {"class": "num" + (c.best_lap === fastest ? " pb" : "")}, c.best_lap ? t(c.best_lap) : "-"));
    tr.appendChild(el("td", {"class": "num"}, c.top_speed ? Math.round(c.top_speed) + " km/h" : "-"));
    tr.appendChild(el("td", {"class": "num"}, c.best_finish ? "P" + c.best_finish : "-"));
    tr.appendChild(el("td", {"class": "num"}, c.avg_finish ? c.avg_finish.toFixed(1) : "-"));
    tr.appendChild(el("td", {"class": "num"}, String(c.wins)));
    body.appendChild(tr);
  });
  tb.appendChild(body);
}
function drawCarStrengths(){
  var C = (D.cars || []).filter(function(c){ return c.s1_delta != null || c.apex_delta_slow != null; });
  var tb = $("carstrengths"), tt = $("carturns");
  [tb, tt].forEach(function(x){ while (x.firstChild) x.removeChild(x.firstChild); });
  if (C.length < 2) return;
  var cols = [["s1_delta", "S1", -1, "s"], ["s2_delta", "S2", -1, "s"], ["s3_delta", "S3", -1, "s"],
              ["apex_delta_slow", "Slow corners", 1, "kmh"], ["apex_delta_medium", "Medium corners", 1, "kmh"], ["apex_delta_fast", "Fast corners", 1, "kmh"]];
  cols = cols.filter(function(k){ return C.some(function(c){ return c[k[0]] != null; }); });
  var bestOf = {};
  cols.forEach(function(k){
    var vals = C.filter(function(c){ return c[k[0]] != null; });
    if (vals.length) bestOf[k[0]] = vals.reduce(function(a, b){ return (b[k[0]] * k[2] > a[k[0]] * k[2]) ? b : a; }).car;
  });
  var head = el("thead"), hr = el("tr");
  hr.appendChild(el("th", null, "Car")); cols.forEach(function(k){ hr.appendChild(el("th", {"class": "num"}, k[1])); });
  head.appendChild(hr); tb.appendChild(head);
  var body = el("tbody");
  C.forEach(function(c){
    var tr = el("tr"); tr.appendChild(el("td", null, c.car));
    cols.forEach(function(k){
      var v = c[k[0]];
      var txt = v == null ? "-" : k[3] === "s" ? (v > 0 ? "+" : "") + v.toFixed(3) : (v > 0 ? "+" : "") + v.toFixed(1) + " km/h";
      var good = v != null && v * k[2] > 0.0005, best = bestOf[k[0]] === c.car;
      tr.appendChild(el("td", {"class": "num" + (best ? " bestcell" : good ? " gain" : v != null && v * k[2] < -0.0005 ? " lose" : "")}, txt));
    });
    body.appendChild(tr);
  });
  tb.appendChild(body);
  // turn by turn: rows are turns, columns are cars
  var turns = (D.car_extra || {}).turns || [];
  if (!turns.length) return;
  var h2 = el("thead"), r2 = el("tr");
  ["Turn", "Type"].forEach(function(x){ r2.appendChild(el("th", null, x)); });
  C.forEach(function(c){ r2.appendChild(el("th", {"class": "num"}, c.car)); });
  h2.appendChild(r2); tt.appendChild(h2);
  var b2 = el("tbody");
  turns.forEach(function(tn){
    var tr = el("tr");
    tr.appendChild(el("td", null, el("b", null, tn.corner)));
    tr.appendChild(el("td", {"class": "muted"}, tn.type + ", " + Math.round(tn.field_kph) + " km/h"));
    var vals = C.map(function(c){ return c.corners ? c.corners[tn.corner] : null; });
    var mx = Math.max.apply(null, vals.filter(function(v){ return v != null; }));
    vals.forEach(function(v){ tr.appendChild(el("td", {"class": "num" + (v != null && v === mx ? " bestcell" : "")}, v == null ? "-" : v.toFixed(1))); });
    b2.appendChild(tr);
  });
  tt.appendChild(b2);
}
var styleMode = D.racing_mode || "reduced";
Array.prototype.forEach.call(document.querySelectorAll(".stylemodes .chip"), function(b){
  b.setAttribute("aria-pressed", String(b.dataset.mode === styleMode));
  b.addEventListener("click", function(){ styleMode = b.dataset.mode;
    Array.prototype.forEach.call(document.querySelectorAll(".stylemodes .chip"), function(x){ x.setAttribute("aria-pressed", String(x === b)); }); drawStyle(); });
});
drawStyle();

// ---------------------------------------------------------------- pass log
function drawPassLog(){
  if (!$("passlog")) return;
  var tb = $("passlog"); while (tb.firstChild) tb.removeChild(tb.firstChild);
  var head = el("thead"), hr = el("tr");
  ["Lap", "Corner", "Who", "Passed", "Kind"].concat(D.embedded ? [""] : []).forEach(function(h){ hr.appendChild(el("th", null, h)); });
  head.appendChild(hr); tb.appendChild(head);
  var body = el("tbody");
  var rows = focus ? D.passes.filter(function(p){ return p.passer === focus || p.passed === focus; }) : D.passes;
  rows.forEach(function(p){
    var tr = el("tr");
    tr.appendChild(el("td", null, "L" + p.lap));
    tr.appendChild(el("td", null, p.corner || "-"));
    [p.passer, p.passed].forEach(function(n){
      var td = el("td"); if (isHuman(n)) { var dot = el("span", {"class": "dot"}); dot.style.background = colorOf(n); td.appendChild(dot); }
      td.appendChild(el("span", {"class": isHuman(n) ? null : "ai-name"}, n)); tr.appendChild(td);
    });
    tr.appendChild(el("td", {"class": "kind k-" + p.kind}, p.kind));
    if (D.embedded) { var wc = el("td"); var wb = watchBtn(Math.max(0, p.t - 5)); if (wb) wc.appendChild(wb); tr.appendChild(wc); }
    body.appendChild(tr);
  });
  if (!rows.length) { var tr = el("tr"); tr.appendChild(el("td", {colspan: 5, "class": "ai-name"}, "No passes.")); body.appendChild(tr); }
  tb.appendChild(body);
  $("passexplain").textContent = focus ? "Passes involving " + focus + "." : D.passes.length + " counted passes, in order.";
}
drawPassLog();

// ---------------------------------------------------------------- lap times
(function lapTimes(){
  var tb = $("laptimes"), L = M.laps, best = Infinity;
  D.drivers.forEach(function(d){ (D.laps[d.name] || []).forEach(function(p){ if (p.valid && p.time < best) best = p.time; }); });
  var head = el("thead"), hr = el("tr"); hr.appendChild(el("th", null, "Driver"));
  for (var l = 1; l <= L; l++) hr.appendChild(el("th", {"class": "num"}, "L" + l));
  head.appendChild(hr); tb.appendChild(head);
  var body = el("tbody");
  D.drivers.forEach(function(d){
    var tr = el("tr"); rowFocus(tr, d.name);
    var nm = el("td"); if (!d.is_ai) { var dot = el("span", {"class": "dot"}); dot.style.background = d.color; nm.appendChild(dot); }
    nm.appendChild(el("span", {"class": d.is_ai ? "ai-name" : null}, d.name)); tr.appendChild(nm);
    var laps = {}; (D.laps[d.name] || []).forEach(function(p){ laps[p.lap] = p; });
    var pb = Math.min.apply(null, (D.laps[d.name] || []).filter(function(p){ return p.valid; }).map(function(p){ return p.time; }).concat([Infinity]));
    for (var l = 1; l <= L; l++) {
      var p = laps[l], cls = "num";
      if (p) { if (!p.valid) cls += " inv"; else if (p.time === best) cls += " fast"; else if (p.time === pb) cls += " pb"; if (p.pit) cls += " pit"; }
      var td = el("td", {"class": cls}, p ? t(p.time) : "");
      if (p && p.s1 != null) td.title = "S1 " + f(p.s1, 3) + "   S2 " + f(p.s2, 3) + "   S3 " + f(p.s3, 3);
      tr.appendChild(td);
    }
    body.appendChild(tr);
  });
  tb.appendChild(body);
})();

// ---------------------------------------------------------------- humans
(function humans(){
  var hs = D.drivers.filter(function(d){ return !d.is_ai; });
  if (!hs.length) { $("humans-sec").hidden = true; return; }
  var tb = $("humans"), head = el("thead"), hr = el("tr");
  var cols = [["Driver", ""], ["Rank", "num"], ["Overall", "num"], ["Start +/-", "num"], ["Lap 1", "num"], ["Passes", "num"],
              ["On friends", "num"], ["Battles won", "num"], ["Median lap", "num"], ["Spread", "num"], ["vs AI", "num"], ["Field", "num"]];
  cols.forEach(function(c){ hr.appendChild(el("th", {"class": c[1]}, c[0])); });
  head.appendChild(hr); tb.appendChild(head);
  var body = el("tbody");
  hs.forEach(function(d){
    var tr = el("tr"); rowFocus(tr, d.name);
    var nm = el("td"); var dot = el("span", {"class": "dot"}); dot.style.background = d.color; nm.appendChild(dot); nm.appendChild(document.createTextNode(d.name)); tr.appendChild(nm);
    [d.human_rank, d.pos, signed(d.positions_gained), signed(d.lap1_gain),
     d.passes_made + " (" + d.passes_gifted + " gifted)", d.passes_on_humans, d.battles_won + " of " + d.battles,
     t(d.median_clean), d.consistency_s == null ? "-" : f(d.consistency_s, 3) + "s", f(d.ai_rel_pace, 3),
     d.field_pct == null ? "-" : Math.round(d.field_pct * 100) + "%"].forEach(function(v){ tr.appendChild(el("td", {"class": "num"}, v == null ? "-" : v)); });
    body.appendChild(tr);
  });
  tb.appendChild(body);
})();

// ---------------------------------------------------------------- battles & pits
(function extras(){
  var B = D.battles.slice().sort(function(a, b){ return b.duration_s - a.duration_s; });
  if (!B.length) $("battles-wrap").hidden = true;
  else {
    var tb = $("battles"), hr = el("tr");
    ["Battle", "Laps", "Average gap", "Swaps", "Came out ahead"].forEach(function(h, i){ hr.appendChild(el("th", {"class": i ? "num" : ""}, h)); });
    var head = el("thead"); head.appendChild(hr); tb.appendChild(head);
    var body = el("tbody");
    B.forEach(function(b){
      var tr = el("tr");
      tr.appendChild(el("td", null, b.a + " vs " + b.b));
      tr.appendChild(el("td", {"class": "num"}, "L" + b.start_lap + "-" + b.end_lap));
      tr.appendChild(el("td", {"class": "num"}, f(b.avg_gap_s != null ? b.avg_gap_s : b.min_gap_s, 2) + "s"));
      tr.appendChild(el("td", {"class": "num"}, b.swaps));
      tr.appendChild(el("td", {"class": "num"}, b.winner));
      body.appendChild(tr);
    });
    tb.appendChild(body);
  }
  if (!D.pits.length) $("pits-wrap").hidden = true;
  else {
    var tp = $("pits"), hr2 = el("tr");
    ["Driver", "Lap", "Pit lane", "Stopped", "Type"].forEach(function(h, i){ hr2.appendChild(el("th", {"class": i ? "num" : ""}, h)); });
    var head2 = el("thead"); head2.appendChild(hr2); tp.appendChild(head2);
    var body2 = el("tbody");
    D.pits.forEach(function(p){
      var tr = el("tr");
      [p.name, p.lap, f(p.lane_time, 1) + "s", f(p.stationary_time, 1) + "s", p.kind.replace("_", " ")]
        .forEach(function(v, i){ tr.appendChild(el("td", {"class": i ? "num" : ""}, v)); });
      body2.appendChild(tr);
    });
    tp.appendChild(body2);
  }
  if (!B.length && !D.pits.length) $("extras").hidden = true;
})();

// ---------------------------------------------------------------- notes & footer
var notes = [];
(M.warnings || []).forEach(function(w){ notes.push(w); });
if (M.out_of_range && M.out_of_range.length) notes.push("The game sent out-of-range values for " + M.out_of_range.join(", ") + "; they were cleaned before analysis.");
$("notes").textContent = notes.length ? "Notes: " + notes.join(" ") : "";
$("footer").textContent = "Recorded by " + M.recorded_by + ". Source: " + M.folder + ". Made with ams2season.";

// ---------------------------------------------------------------- every table: click a column heading to sort
function sortValue(td) {
  var t = (td ? td.innerText || td.textContent : "").trim();
  if (!t || t === "-" || t === "\u2013" || t === "never") return null;
  var m = t.match(/^(\d+):(\d{2}(?:\.\d+)?)/); if (m) return {n: +m[1] * 60 + parseFloat(m[2])};
  m = t.replace(/\u2212/g, "-").match(/^[+-]?\d+(?:\.\d+)?/); if (m) return {n: parseFloat(m[0])};
  m = t.match(/^P(\d+)/); if (m) return {n: +m[1]};
  return {s: t};
}
document.addEventListener("click", function (e) {
  var th = e.target.closest && e.target.closest("thead th");
  if (!th || e.target.closest("a,button,input,select,label")) return;
  var table = th.closest("table");
  if (!table || table.classList.contains("nosort") || !table.tBodies.length) return;
  var idx = 0, sib = th;
  while ((sib = sib.previousElementSibling)) idx += sib.colSpan || 1;
  var body = table.tBodies[0], rows = Array.prototype.slice.call(body.rows);
  var pinned = rows.filter(function (r) { return r.classList.contains("fieldrow"); });
  rows = rows.filter(function (r) { return !r.classList.contains("fieldrow"); });
  var dir = th.getAttribute("data-sort") === "asc" ? "desc" : "asc";
  Array.prototype.forEach.call(table.querySelectorAll("thead th"), function (x) { x.removeAttribute("data-sort"); });
  th.setAttribute("data-sort", dir);
  var vals = rows.map(function (r) { return sortValue(r.cells[idx]); });
  var nonNull = vals.filter(Boolean), numeric = nonNull.length && nonNull.filter(function (v) { return v.n !== undefined; }).length >= 0.6 * nonNull.length;
  var sign = dir === "asc" ? 1 : -1;
  rows.map(function (r, i) { return {r: r, v: vals[i], i: i}; }).sort(function (a, b) {
    if (!a.v && !b.v) return a.i - b.i;
    if (!a.v) return 1;
    if (!b.v) return -1;
    var c = numeric ? ((a.v.n === undefined ? Infinity : a.v.n) - (b.v.n === undefined ? Infinity : b.v.n))
      : String(a.v.s || a.v.n).localeCompare(String(b.v.s || b.v.n), undefined, {numeric: true, sensitivity: "base"});
    return c ? c * sign : a.i - b.i;
  }).forEach(function (x) { body.appendChild(x.r); });
  pinned.forEach(function (r) { body.insertBefore(r, body.firstChild); });
});

// ---------------------------------------------------------------- full screen for every figure
["lapchart", "gapchart", "map"].forEach(function(id){
  if (!$(id)) return;  // e.g. the pass map, which lives on the Overtaking page now
  var panel = $(id).closest(".panel"); if (!panel || !panel.requestFullscreen) return;
  panel.classList.add("fsable");
  var b = el("button", {"class": "fsbtn", title: "Full screen (or double-click the figure)"}, "Full screen");
  function toggle(){ if (document.fullscreenElement) document.exitFullscreen(); else panel.requestFullscreen().catch(function(){}); }
  b.addEventListener("click", function(e){ e.stopPropagation(); toggle(); });
  panel.addEventListener("dblclick", function(e){ if (e.target.closest("button")) return; toggle(); });
  panel.appendChild(b);
});
document.addEventListener("fullscreenchange", function(){
  document.querySelectorAll(".fsbtn").forEach(function(b){ b.textContent = document.fullscreenElement === b.parentNode ? "Exit full screen" : "Full screen"; });
});
})();
</script>
</body>
</html>
"""
