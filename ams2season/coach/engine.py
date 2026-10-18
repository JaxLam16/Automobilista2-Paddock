"""Causal coaching decisions. Every input is available at the current tick only."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from collections import Counter

from .catalogue import CATALOGUE
from .model import Context, Evidence, Message, Requirement, finite, incident
from .radio import Scheduler
from .numbers import Numbers
from .gaps import GapWatch
from .fuel import FuelWatch
from .race_length import RaceLengthWatch
from .apex import ApexWatch
from .corner_speed import CornerSpeedWatch
from .braking import BrakingWatch
from .sections import SectionLossWatch, spoken as section_slots
from .offtrack import OffTrackWatch
from .car_status import FuelLeftWatch, HealthWatch, LapWatch, ReconGuide, TempWatch
from .numbers import integer_words
import re
from .windows import WindowLearner, weather_key
from .. import shm as S


def relations(tick, player):
    if not player or not player.car_class:
        return {}
    field = sorted((c for c in tick.cars if c.car_class == player.car_class and c.position > 0
                    and c.race_state in (S.RACESTATE_RACING, S.RACESTATE_NOT_STARTED, S.RACESTATE_FINISHED)),
                   key=lambda c: c.position)
    if (len({c.position for c in field}) != len(field) or player not in field):
        return {}
    index = field.index(player)
    result = {"class leader": field[0].identity}
    if index > 0:
        result["car ahead"] = field[index - 1].identity
    if index + 1 < len(field):
        result["car behind"] = field[index + 1].identity
    return result


@dataclass
class PitState:
    t: float
    pit: int
    road_since: float | None
    entry: float | None = None
    relation: str | None = None
    announced: bool = False


class PitWatch:
    """Require actual on-track -> pit-entry evidence, then half a second stability."""
    def __init__(self):
        self.states = {}
        self.previous_relations = {}

    def feed(self, tick, current_relations):
        events = []
        fresh = {}
        for car in tick.cars:
            previous = self.states.get(car.identity)
            state = PitState(tick.t, car.pit, tick.t if car.pit == 0 else None)
            if previous is not None and 0 < tick.t - previous.t <= .5:
                if car.pit == 0:
                    state.road_since = previous.road_since if previous.pit == 0 else tick.t
                elif car.pit in (1, 2):
                    if (previous.pit == 0 and previous.road_since is not None
                            and tick.t - previous.road_since >= .5 and car.race_state == S.RACESTATE_RACING):
                        state.entry = tick.t
                        state.relation = next((r for r in ("car ahead", "car behind", "class leader")
                                               if self.previous_relations.get(r) == car.identity), None)
                    elif previous.pit in (1, 2):
                        state.entry, state.relation, state.announced = previous.entry, previous.relation, previous.announced
                    if (state.entry is not None and not state.announced and state.relation
                            and tick.t - state.entry >= .5):
                        state.announced = True
                        if current_relations.get(state.relation) == car.identity:
                            events.append((car, state.relation, state.entry))
            fresh[car.identity] = state
        self.states = fresh
        self.previous_relations = dict(current_relations)
        return events


class CoachEngine:
    @staticmethod
    def capabilities():
        return {'stage':'development_preview','implemented_rules':[
            {'id':'X-15','label':'Observed rival pit entry','sessions':['race']},
            {'id':'G-18','label':'Measured gap-behind trends','sessions':['race']},
            {'id':'G-01','label':'Measured gap ahead and change per lap','sessions':['race']},
            {'id':'S-16','label':'Measured practice fuel use','sessions':['practice']},
            {'id':'C-09','label':'Practice corner minimum-speed comparisons','sessions':['practice']},
            {'id':'C-05','label':'Measured earlier practice brake inputs','sessions':['practice']},
            {'id':'C-10','label':'Mapped practice apex patterns','sessions':['practice']},
            {'id':'C-01','label':'Biggest repeated practice section loss','sessions':['practice']},
            {'id':'C-26','label':'Running wide on a lap that still counts','sessions':['practice','qualify','race']},
            {'id':'C-35','label':'Lap time at the line against your best','sessions':['practice','qualify','race']},
            {'id':'Q-09','label':'Lap deleted by the game','sessions':['practice','qualify','race']},
            {'id':'W-02','label':'Cold tyres or brakes leaving the pits','sessions':['practice','qualify','race']},
            {'id':'W-05','label':'Tyres up to temperature','sessions':['practice','qualify','race']},
            {'id':'M-02','label':'Hot or cooled tyres','sessions':['practice','qualify','race']},
            {'id':'M-10','label':'Hot brakes (iron-brake classes)','sessions':['practice','qualify','race']},
            {'id':'M-17','label':'Low fuel: laps left','sessions':['practice','qualify','race']},
            {'id':'M-23','label':'Damage after a hit','sessions':['practice','qualify','race']},
            {'id':'M-13','label':'Engine temperatures high','sessions':['practice','qualify','race']},
            {'id':'C-30','label':'Five consistent laps','sessions':['practice']},
            {'id':'V-25','label':'Recon lap on request','sessions':['practice','qualify','race']},
            {'id':'B-01','label':'Practice session goal question','sessions':['practice']},
            {'id':'B-08','label':'Run plan before leaving the pits','sessions':['practice']},
            {'id':'C-43','label':'Live R&D objective progress','sessions':['practice']},
            {'id':'S-03','label':'Setup suggestions after a Practice 1 run','sessions':['practice']},
            {'id':'D-01','label':'Objective debrief after a Practice 2 run','sessions':['practice']},
            {'id':'V-24','label':'Answers to your radio or typed replies','sessions':['practice']}],
            'implemented_measurements':[{'id':'P-02','label':'Overall leader finish-lap estimate; fuel plan pending'}],
            'not_yet_available':['Race/qualifying apex coaching','Braking and throttle advice','Corner pace comparisons','Pit strategy and rejoin forecasts']}

    def __init__(self, driver, scheduler=None, *, window_store=None, numbers=None,apex_store=None,program=None,
                 tyre_window=None, corner_list=None, name_for=None):
        if not driver or not driver.strip():
            raise ValueError("Choose the driver's exact in-game name.")
        self.driver = driver.strip()
        self.name_for = name_for
        self.personal_name = ''
        self.last_personal_call = float('-inf')
        self.radio = scheduler or Scheduler()
        self.pits = PitWatch()
        self.gaps = GapWatch()
        self.ahead_gaps = GapWatch('car ahead',clean_intervals=False,max_gap_s=120)
        self.fuel = FuelWatch()
        self.race_length = RaceLengthWatch()
        self.race_length_signature = None
        self.apex = ApexWatch()
        self.apex_store = apex_store
        self.corner_speed = CornerSpeedWatch()
        self.braking = BrakingWatch()
        self.sections = SectionLossWatch()
        self.offtrack = OffTrackWatch()
        self.laps = LapWatch()
        self.temps = TempWatch(tyre_window)
        self.fuel_left = FuelLeftWatch()
        self.recon = ReconGuide()
        self.health = HealthWatch()
        self.lap_history = []          # (lap, time, valid) for consistency
        self.consistency_lap = -100
        self.corner_list = corner_list      # fallback corner source: the setup engineer's corners
        self.geometry = None
        self.windows = None
        self.session_key = None
        self.previous = None
        self.last_incident = None
        self.sequence = 0
        self.context = None
        self.ticks = 0
        self.window_store = window_store
        self.window_identity = None
        self.window_cache_error = None
        self.numbers = numbers or Numbers()
        # Practice programme (goal question, briefs, objectives, debriefs): live coach only.
        self.program = program
        self.diagnostics = Counter()
        self.inactive_reasons = Counter()

    def build_context(self, tick, player, radio_busy):
        active, reason = True, "active"
        if not tick.fresh:
            active, reason = False, "disconnected"
        elif tick.game_state != S.GAME_INGAME_PLAYING:
            reason = {S.GAME_INGAME_PAUSED: "paused", S.GAME_INGAME_REPLAY: "replay",
                      S.GAME_FRONT_END_REPLAY: "replay"}.get(tick.game_state, "menus")
            active = False
        elif tick.session not in ("race", "practice", "qualify", "time_attack"):
            active, reason = False, "invalid_session"
        elif tick.length <= 0 or player is None or player.laps < 0:
            active, reason = False, "driver_unknown"
        elif tick.viewed_slot != player.slot:
            active, reason = False, "spectating"
        elif player.race_state in (S.RACESTATE_DISQUALIFIED, S.RACESTATE_RETIRED, S.RACESTATE_DNF):
            active, reason = False, "driver_retired"
        elif player.race_state == S.RACESTATE_FINISHED:
            active, reason = False, 'finished'
        related = relations(tick, player)
        facts = {"driver": player.identity if player else None}
        facts.update({"relation:" + r: ident for r, ident in related.items()})
        for car in tick.cars:
            facts["pit:" + car.identity] = car.pit
        gap, traffic_known = None, True
        if player and player.distance is not None and tick.length > 0:
            gaps = []
            for car in tick.cars:
                if car.identity == player.identity or car.pit in (1, 2, 3, 4, 5):
                    continue
                if car.distance is None or car.distance > tick.length:
                    traffic_known = False
                    continue
                d = abs(car.distance - player.distance) % tick.length
                # A conservative workload proxy, not a racing gap or catch forecast.
                gaps.append(min(d, tick.length-d) / max(finite(tick.local.get("speed"), 0), car.speed or 0, 10))
            gap = min(gaps) if gaps else 1000000
        else:
            traffic_known = False
        facts["traffic_known"] = traffic_known
        if self.last_incident is None or incident(tick.local.get("crash_state", -1)):
            self.last_incident = tick.t
        speed = finite(tick.local.get("speed"))
        garage_menu = (tick.game_state == S.GAME_INGAME_INMENU_TIME_TICKING and tick.fresh and player is not None
                       and player.pit in (2, 4) and tick.viewed_slot == player.slot
                       and tick.session in ("race", "practice", "qualify"))
        pit_radio = bool(player is not None and player.pit in (1, 2, 3, 4, 5) and speed is not None
                         and speed <= 25 and (active or garage_menu))
        return Context(t=tick.t, session_id=tick.session_id, session=tick.session,
                       lap=player.laps+1 if player else 1, distance=player.distance if player else None,
                       active=active, reason=reason, speed=finite(tick.local.get("speed")),
                       throttle=finite(tick.local.get("throttle")), brake=finite(tick.local.get("brake")),
                       steering=finite(tick.local.get("steering")), pit=player.pit if player else -1,
                       rain=finite(tick.local.get("rain_density")), nearest_gap=gap,
                       since_incident=max(0, tick.t-self.last_incident),
                       # Conservative quali default: any flying on-track lap is a push.
                       qualifying_push=bool(tick.session == "qualify" and player and player.laps >= 1 and player.pit == 0),
                       window_s=self.windows.seconds(player.distance, finite(tick.local.get("speed")))
                           if self.windows and player else None,
                       window_id=self.windows.window_id(player.distance,tick.t)
                           if self.windows and player and active else None,
                       radio_busy=radio_busy, facts=facts, pit_radio=pit_radio)

    def feed(self, tick, *, radio_busy=None):
        player = tick.player(self.driver)
        key = (tick.session_id, tick.track, tick.layout, tick.length, player.identity if player else None,
               weather_key(tick.local.get('rain_density')))
        changed = key != self.session_key
        discontinuity = (self.previous is not None and not 0 < tick.t - self.previous.t <= .5)
        if changed:
            self.pits, self.last_incident = PitWatch(), None
            self.gaps.clear()
            self.ahead_gaps.clear()
            self.fuel.clear('session_changed',keep_history=False)
            self.race_length.clear('session_changed',keep_history=False)
            self.race_length_signature = None
            self.apex.clear('session_changed')
            self.corner_speed.clear('session_changed')
            self.braking.clear('session_changed')
            self.sections.clear('session_changed')
            self.offtrack.clear('session_changed')
            self.laps.clear(keep_best=False)
            self.recon.stop()
            self.health.clear()
            self.lap_history, self.consistency_lap = [], -100
            self.temps.clear()
            self.fuel_left.clear()
            self.windows = WindowLearner(tick.length) if tick.length >= 100 else None
            self.session_key = key
            self.window_identity = self.window_store.identity(tick,player) if self.window_store else None
            self.window_cache_error = None
            if self.window_store and self.windows:
                try:
                    self.window_store.load(self.window_identity,self.windows)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    # A corrupt/old derived cache must not stop fresh learning.
                    self.window_cache_error = str(exc)
        elif discontinuity:
            self.pits = PitWatch()
            self.gaps.clear()
            self.ahead_gaps.clear()
            self.fuel.clear('telemetry_gap')
            self.race_length.clear('telemetry_gap')
            self.offtrack.current = self.offtrack.pending = None
            self.laps.clear()
            self.fuel_left.clear()
            if self.windows:
                self.windows.clear_current()
        ctx = self.build_context(tick, player, radio_busy)
        program = self.program
        if program is not None:
            if tick.session_id != program.session_id or (program.detected is None and tick.session == 'practice'
                                                          and player is not None):
                program.begin(tick, player)
            program.update_facts(ctx)
        previous_speed_interval=self.corner_speed.last_interval
        speed_patterns=self.corner_speed.feed(tick,player,active=ctx.active,reason=ctx.reason)
        previous_brake_interval=self.braking.last_interval
        brake_patterns=self.braking.feed(tick,player,active=ctx.active,reason=ctx.reason)
        for key in self.braking.patterns:
            ctx.facts['early_brake:'+key]=self.braking.token(key,tick,player)
        if self.braking.last_interval is not None and self.braking.last_interval is not previous_brake_interval:
            self.radio.log.record('braking_interval_checked',ctx,code='C-05',
                text='Local full-lap interval checked for repeated earlier brake inputs.',
                evidence=asdict(Evidence('high',{**self.braking.last_interval,
                    'comparison_reason':self.braking.comparison_reason,'checks':self.braking.checks})))
        for key in self.corner_speed.patterns:
            ctx.facts['corner_speed:'+key]=self.corner_speed.token(key,tick,player)
        section_patterns=[]
        if not ctx.active or tick.session!='practice':
            self.sections.patterns={}
        elif self.corner_speed.last_interval is not None and self.corner_speed.last_interval is not previous_speed_interval:
            # Same interval, same bends as C-09; only this interval's C-05 result can add a braking fact.
            section_patterns=self.sections.evaluate(self.corner_speed,tick,{p['key']:p for p in brake_patterns})
            self.radio.log.record('section_loss_interval_checked',ctx,code='C-01',
                text='Local full-lap interval checked for the biggest repeated section loss.',
                evidence=asdict(Evidence('high',{'reason':self.sections.reason,'ranking':self.sections.ranking[:5]})))
        for key in self.sections.patterns:
            ctx.facts['section_loss:'+key]=self.sections.token(key,tick,player)
        wide_patterns=self.offtrack.feed(tick,player,active=ctx.active,reason=ctx.reason)
        for key in self.offtrack.patterns:
            ctx.facts['wide:'+key]=self.offtrack.token(key,tick,player)
        if self.corner_speed.last_interval is not None and self.corner_speed.last_interval is not previous_speed_interval:
            self.radio.log.record('corner_speed_interval_checked',ctx,code='C-09',
                text='Local full-lap interval checked for repeated corner-speed changes.',
                evidence=asdict(Evidence('high',self.corner_speed.last_interval)))
        geometry=self.apex_store.load(tick.track,tick.layout,tick.length) if self.apex_store else None
        self.geometry = geometry
        status_events = []
        lap_event = self.laps.feed(tick, player, active=ctx.active)
        if lap_event:
            status_events.append(lap_event)
        status_events += self.temps.feed(tick, player, active=ctx.active)
        status_events += self.health.feed(tick, player, active=ctx.active)
        recon = self.recon.feed(tick, player, active=ctx.active)
        if recon:
            status_events.append(recon)
        previous_apex_interval=self.apex.last_interval
        apex_patterns=self.apex.feed(tick,player,geometry,active=ctx.active,reason=ctx.reason)
        for corner in geometry.corners if geometry else ():
            ctx.facts['apex:pattern:'+corner['name']]=self.apex.token(corner['name'],tick,player)
        if self.apex.last_interval is not None and self.apex.last_interval is not previous_apex_interval:
            self.radio.log.record('apex_interval_checked',ctx,code='C-10',
                text='Local full-lap interval checked for mapped apex patterns.',
                evidence=asdict(Evidence('high',{'map_sha256':geometry.digest,**self.apex.last_interval})))
        race_length = self.race_length.feed(tick,player,active=ctx.active,reason=ctx.reason)
        if race_length:
            signature = (race_length['leader'],race_length['state'],
                         race_length['finish_lap_low'],race_length['finish_lap_high'])
            if signature != self.race_length_signature:
                self.race_length_signature = signature
                self.radio.log.record('race_length_updated',ctx,code='P-02',
                    text=('Overall leader '+('finish observed' if race_length['state']=='observed_finish' else
                        'scheduled finish' if race_length['state']=='scheduled' else 'estimated finish')+
                        ' on lap '+str(race_length['finish_lap_low'])+
                        ('–'+str(race_length['finish_lap_high']) if race_length['finish_lap_high']!=race_length['finish_lap_low'] else '')+'.'),
                    evidence=asdict(Evidence('high' if race_length['state']!='estimated' else 'medium',race_length)))
        gap_trend = None
        ahead_trend = None
        fuel_calibration = None
        if ctx.active:
            behind = next((c for c in tick.cars if c.identity == ctx.facts.get('relation:car behind')), None)
            gap_trend = self.gaps.feed(tick, player, behind)
            ahead = next((c for c in tick.cars if c.identity == ctx.facts.get('relation:car ahead')), None)
            ahead_trend = self.ahead_gaps.feed(tick, player, ahead)
            fuel_calibration = self.fuel.feed(tick, player)
            fuel_low = self.fuel_left.feed(tick, player, self.fuel.estimate(tick.t))
            if fuel_low:
                status_events.append(fuel_low)
        else:
            self.gaps.clear()
            self.ahead_gaps.clear()
            self.fuel.clear(ctx.reason)
        ctx.facts['timing:gap_behind'] = self.gaps.token(tick.t)
        ctx.facts['timing:gap_ahead'] = self.ahead_gaps.token(tick.t)
        ctx.facts['fuel:calibration'] = self.fuel.token(tick.t)
        self.diagnostics['active_ticks'] += int(ctx.active)
        self.diagnostics['active_practice_ticks'] += int(ctx.active and tick.session == 'practice')
        if not ctx.active:
            self.inactive_reasons[ctx.reason] += 1
        if ctx.active and tick.session=='race':
            self.diagnostics['active_race_ticks'] += 1
            self.diagnostics['racing_pit_entry_samples'] += sum(
                c.pit in (1,2) and c.race_state==S.RACESTATE_RACING for c in tick.cars)
        self.diagnostics['usable_radio_window_ticks'] += int(bool(ctx.active and ctx.window_s and ctx.window_s>0))
        if changed or discontinuity:
            if program is not None and not changed:
                program.radio_reset(self.radio)  # before the reset forgets what was already said
            self.radio.reset(ctx, "session_changed" if changed else "telemetry_gap")
        self.radio.advance(ctx)
        if ctx.active:
            summarised=set()
            for pattern in section_patterns:
                self.diagnostics['confirmed_section_losses']+=1;self.sequence+=1
                spec=CATALOGUE['C-01'];key=pattern['key']
                slots=section_slots(self.numbers,pattern,spec.phrases)
                if self.radio.offer(Message(f'C-01:{self.sequence}',spec,tick.session_id,tick.t,tick.t+spec.ttl_s,
                        'section_loss:'+key,slots,
                        Evidence('high',{'driver':player.identity,'spoken_fact':slots['detail'][2:] or None,**pattern},
                                 pattern_laps=tuple(pattern['pattern_laps']),loss_s=pattern['loss_s'],
                                 severity=pattern['loss_s']),
                        (Requirement('section_loss:'+key,pattern['token']),Requirement('driver',player.identity)),
                        corner='Bend near '+str(pattern['distance_m'])+' m',last_lap=ctx.lap),ctx):
                    # C-01 already carries this bend's facts; avoid a second call about it.
                    summarised.add(key)
            for pattern in wide_patterns:
                self.diagnostics['confirmed_offtrack_warnings']+=1;self.sequence+=1
                spec=CATALOGUE['C-26'];key=pattern['key']
                place='near '+self.numbers.distance_m(round(pattern['distance_m']/50)*50).speech
                self.radio.offer(Message(f'C-26:{self.sequence}',spec,tick.session_id,tick.t,tick.t+spec.ttl_s,
                    'wide:'+key,{'place':place},
                    Evidence('high',{'driver':player.identity,**pattern},severity=max(e['seconds'] for e in pattern['episodes'])),
                    (Requirement('wide:'+key,pattern['token']),Requirement('driver',player.identity)),
                    corner='Near '+str(pattern['distance_m'])+' m',last_lap=ctx.lap),ctx)
            for pattern in brake_patterns:
                self.diagnostics['confirmed_early_brake_patterns']+=1
                if pattern['key'] in summarised:continue
                self.sequence+=1
                spec=CATALOGUE['C-05'];key=pattern['key']
                turn='the bend near '+self.numbers.distance_m(pattern['distance_m']).speech
                misses=[r for r in pattern['recent'] if r['earlier_at_least_m']>=8 and r['entry_down_kph']>=4
                    and r['slower_by_s']>=.15 and r['approach_comparable']]
                self.radio.offer(Message(f'C-05:{self.sequence}',spec,tick.session_id,tick.t,tick.t+spec.ttl_s,
                    'early_brake:'+key,{'turn':turn,'amount':self.numbers.distance_m(pattern['earlier_by_m']).speech},
                    Evidence('high',{'driver':player.identity,**pattern},pattern_laps=tuple(r['lap'] for r in misses),
                             loss_s=min(r['slower_by_s'] for r in misses),severity=pattern['earlier_by_m']),
                    (Requirement('early_brake:'+key,pattern['token']),Requirement('driver',player.identity)),
                    corner='Bend near '+str(pattern['distance_m'])+' m',last_lap=ctx.lap),ctx)
            for pattern in speed_patterns:
                # One observation for the same bend; the brake comparison includes speed/timing evidence.
                if pattern['key'] in {p['key'] for p in brake_patterns}:continue
                self.diagnostics['confirmed_corner_speed_patterns']+=1
                if pattern['key'] in summarised:continue
                self.sequence+=1
                spec=CATALOGUE['C-09'];key=pattern['key']
                turn='the bend near '+self.numbers.distance_m(pattern['distance_m']).speech
                misses=[r for r in pattern['recent'] if r['minimum_down_kph']>=4 and r['slower_by_s']>=.15]
                self.radio.offer(Message(f'C-09:{self.sequence}',spec,tick.session_id,tick.t,tick.t+spec.ttl_s,
                    'corner_speed:'+key,{'turn':turn},
                    Evidence('high',{'driver':player.identity,**pattern},pattern_laps=tuple(r['lap'] for r in misses),
                             loss_s=min(r['slower_by_s'] for r in misses),severity=pattern['minimum_down_kph']),
                    (Requirement('corner_speed:'+key,pattern['token']),Requirement('driver',player.identity)),
                    corner='Bend near '+str(pattern['distance_m'])+' m',last_lap=ctx.lap),ctx)
            for pattern in apex_patterns:
                self.diagnostics['confirmed_apex_patterns'] += 1
                self.sequence += 1
                spec=CATALOGUE['C-10'];name=pattern['corner']
                numbered=re.fullmatch(r'T(\d{1,3})',name,re.IGNORECASE)
                turn='turn '+integer_words(int(numbered[1])) if numbered else name
                misses=[r for r in pattern['recent'] if r['wider_by_m']>=1.5 and r['slower_by_s']>=.15]
                self.radio.offer(Message(f'C-10:{self.sequence}',spec,tick.session_id,tick.t,
                    tick.t+spec.ttl_s,'apex:'+name,{'turn':turn},
                    Evidence('high',{'driver':player.identity,'causal_time_loss_attributed_to_line':False,**pattern},
                        pattern_laps=tuple(r['lap'] for r in misses),
                        loss_s=min(r['slower_by_s'] for r in misses),severity=pattern['wider_by_m']),
                    (Requirement('apex:pattern:'+name,pattern['token']),Requirement('driver',player.identity)),
                    corner=name,last_lap=ctx.lap),ctx)
            if ahead_trend:
                self.diagnostics['confirmed_ahead_gap_trends'] += 1
                self.sequence += 1
                spec = CATALOGUE['G-01']
                trend = ('held steady' if ahead_trend['trend']=='steady' else
                    ('shrank ' if ahead_trend['trend']=='closing' else 'grew ')+
                    self.numbers.gap(abs(ahead_trend['change_per_lap_s'])).speech+' per lap')
                self.radio.offer(Message(f'G-01:{self.sequence}',spec,tick.session_id,tick.t,
                    ahead_trend['measured_t']+spec.ttl_s,f"gap_ahead:{ahead_trend['rival']}",
                    {'gap':self.numbers.gap(ahead_trend['gap_s']).speech,'trend':trend},
                    Evidence('high',{'source':'matched_midpoint_crossings',**ahead_trend}),
                    (Requirement('timing:gap_ahead',ahead_trend['token']),
                     Requirement('relation:car ahead',ahead_trend['rival']))),ctx)
            if fuel_calibration:
                self.diagnostics['confirmed_fuel_calibrations'] += 1
                fuel_evidence = Evidence('high',{'source':'measured_clean_midpoint_laps',**fuel_calibration})
                self.radio.log.record('fuel_calibrated',ctx,code='S-16',
                    text='Measured fuel use '+self.numbers.fuel_burn(fuel_calibration['litres_per_lap']).text+'.',
                    evidence=asdict(fuel_evidence))
                if tick.session == 'practice':
                    self.diagnostics['fuel_call_candidates'] += 1
                    self.sequence += 1
                    spec = CATALOGUE['S-16']
                    self.radio.offer(Message(f'S-16:{self.sequence}',spec,tick.session_id,tick.t,
                        tick.t+spec.ttl_s,'practice_fuel_use',
                        {'use':self.numbers.fuel_burn(fuel_calibration['litres_per_lap']).speech},
                        fuel_evidence,
                        (Requirement('fuel:calibration',fuel_calibration['token']),)),ctx)
            for event in status_events:
                self._car_status(event, tick, player, ctx)
            if gap_trend:
                self.diagnostics['confirmed_gap_trends'] += 1
                self.sequence += 1
                spec = CATALOGUE['G-18']
                self.radio.offer(Message(f'G-18:{self.sequence}',spec,tick.session_id,tick.t,
                    gap_trend['measured_t']+spec.ttl_s,f"gap_behind:{gap_trend['rival']}",
                    {'gap':self.numbers.gap(gap_trend['gap_s']).speech,
                     'trend':{'steady':'steady','closing':'closing','opening':'growing'}[gap_trend['trend']]},
                    Evidence('high',{'source':'matched_midpoint_crossings',**gap_trend}),
                    (Requirement('timing:gap_behind',gap_trend['token']),
                     Requirement('relation:car behind',gap_trend['rival']))),ctx)
            if self.windows:
                completed = self.windows.completed
                self.windows.feed(tick, player)
                if self.window_store and self.windows.completed != completed:
                    try:
                        self.window_store.save(self.window_identity,self.windows)
                    except (OSError,ValueError) as exc:
                        self.window_cache_error = str(exc)
                        self.radio.log.record('window_cache_error',ctx,reason=str(exc))
            for car, relation, entry in self.pits.feed(tick, relations(tick, player)) if tick.session == "race" else ():
                if car.identity == player.identity:
                    continue
                self.diagnostics['observed_relevant_pit_entries'] += 1
                self.sequence += 1
                spec = CATALOGUE["X-15"]
                slots = {"relation": relation}
                if self.name_for is not None:
                    spec = replace(spec, phrases=('{driver} is pitting.', '{driver} is entering the pits.',
                                                   'Pit entry for {driver}.'))
                    slots = {'driver': self.name_for(car)}
                message = Message(f"X-15:{self.sequence}", spec, tick.session_id, tick.t, entry+spec.ttl_s,
                    f"pit:{car.identity}", slots,
                    Evidence("high", {"driver": car.name, "slot": car.slot, "pit_mode": car.pit,
                                      "entry_t": entry, "source": "observed_transition"}),
                    (Requirement("pit:"+car.identity, (1, 2), "in"),
                     Requirement("relation:"+relation, car.identity)),bundle_key='observed_pit_entries')
                self.radio.offer(message, ctx)
        else:
            self.pits = PitWatch()
            if self.windows:
                self.windows.clear_current()
        if program is not None:
            program.feed(tick, player, ctx, self.radio)
        self.previous, self.context = tick, ctx
        self.ticks += 1
        return self.radio.select(ctx)

    # ---------------------------------------------------------------- standalone engineer basics
    def start_recon(self):
        """The driver asked for a recon lap. Returns what the engineer will do."""
        ctx = self.context
        if ctx is None or not ctx.active or self.previous is None:
            return 'Recon needs the car on track with the live coach running.'
        corners = []
        if self.geometry and self.geometry.corners:
            named = sorted((finite(c.get('apex')), str(c['name'])) for c in self.geometry.corners if finite(c.get('apex')) is not None)
            for n, (apex, name) in enumerate(named, 1):
                m = re.fullmatch(r'T(\d{1,3})', name, re.IGNORECASE)
                corners.append((apex, 'turn ' + integer_words(int(m[1]) if m else n) if m or re.fullmatch(r'[A-Z]?\d+', name) else name))
        elif self.corner_list is not None:
            try:
                found = self.corner_list() or []
            except Exception:
                found = []
            apexes = sorted(finite(c.get('apex')) for c in found if finite(c.get('apex')) is not None)
            corners = [(apex, 'turn ' + integer_words(n)) for n, apex in enumerate(apexes, 1)]
        tick = self.previous
        if not self.recon.start(corners):
            self._say('V-25', 'recon:none', ("I don't have a corner map here yet. Do a lap and ask again.",),
                      {'corners': 0}, tick, ctx)
            return 'No corner map for this track yet: do a lap (the setup engineer maps the corners) and ask again.'
        self._say('V-25', 'recon:start', ("Recon lap. I'll call each corner.", "Copy, recon. I'll call the corners.",
                  "Recon lap, corners coming up."), {'corners': len(corners)}, tick, ctx)
        return f'Recon lap: {len(corners)} corners will be called for one lap.'

    def _say(self, code, key, lines, evidence, tick, ctx, **values):
        if self.personal_name and code in ('C-30', 'C-35') and tick.t - self.last_personal_call >= 120:
            lines = [self.personal_name + ', ' + line for line in lines]
            self.last_personal_call = tick.t
        lines = tuple(re.sub(r'(^|[.!?] )([a-z])', lambda m: m[1] + m[2].upper(), line) for line in lines)
        lines = (lines * 3)[:3]
        self.sequence += 1
        spec = CATALOGUE[code]
        message = Message(f'{code}:{self.sequence}', spec, tick.session_id, tick.t, tick.t + values.get('ttl', spec.ttl_s), key,
                          {'a': lines[0], 'b': lines[1], 'c': lines[2]}, Evidence('high', evidence),
                          (Requirement('driver', ctx.facts.get('driver')),) if ctx.facts.get('driver') else (),
                          last_lap=ctx.lap if values.get('this_lap') else None)
        self.diagnostics['status_' + code] += 1
        return self.radio.offer(message, ctx)

    def _consistency(self, event, tick, ctx):
        """C-30: five counted laps in a row within three tenths, at most every eight laps."""
        self.lap_history.append((event['lap'], event['time'], event['valid']))
        self.lap_history = self.lap_history[-5:]
        if tick.session != 'practice' or len(self.lap_history) < 5 or event['lap'] - self.consistency_lap < 8:
            return
        laps = [lap for lap, _, _ in self.lap_history]
        times = [time for _, time, valid in self.lap_history if valid]
        if len(times) < 5 or laps != list(range(laps[0], laps[0] + 5)):
            return
        spread = max(times) - min(times)
        if spread > .3:
            return
        self.consistency_lap = event['lap']
        tenths = max(1, int(-(-spread * 10 // 1)))
        words = integer_words(tenths) + (' tenth' if tenths == 1 else ' tenths')
        self._say('C-30', f"consistency:{event['lap']}", (f'Five laps within {words}. Good rhythm.',
                  f"That's five laps within {words}. Nice and consistent.", f'Five in a row within {words}. Lovely rhythm.'),
                  {'spread_s': round(spread, 3)}, tick, ctx)

    def _temperature(self, celsius):
        value = celsius * 1.8 + 32 if self.numbers.units.temperature == 'f' else celsius
        return integer_words(int(round(max(0, min(1999, value)))))

    def _corner_near(self, distance):
        """'at turn three' for a mapped corner within 250 m behind the car, else ''."""
        if distance is None or not self.geometry:
            return ''
        best = None
        for corner in self.geometry.corners:
            apex = finite(corner.get('apex'))
            if apex is None:
                continue
            gap = distance - apex
            if -60 <= gap <= 250 and (best is None or abs(gap) < abs(best[0])):
                best = (gap, corner['name'])
        if best is None:
            return ''
        numbered = re.fullmatch(r'T(\d{1,3})', best[1], re.IGNORECASE)
        return ' at turn ' + integer_words(int(numbered[1])) if numbered else ''

    def _car_status(self, event, tick, player, ctx):
        kind = event['kind']
        # Original modules own these baseline reports, including their class
        # thresholds and cadence. Keep watcher/program/R&D histories intact.
        if kind=='lap' and getattr(self,'original_lap_times',False):return
        if (kind in ('pit_exit_cold','tyres_ready','tyres_hot','tyres_cooled','brakes_hot')
                and getattr(self,'original_tyre_monitor',False)):return
        evidence = {k: v for k, v in event.items() if isinstance(v, (int, float, str, bool)) or v is None}
        if kind == 'lap':
            time = self.numbers.lap_time(event['time']).speech
            best = event['best_before']
            if not event['valid']:
                lines = ((f'{time}, not counted.',) if event['deleted_said'] else
                         (f"{time}, but that lap's deleted.", f'{time}, deleted, track limits.', f"{time}. That one won't count."))
            elif best is None:
                if tick.session == 'race':
                    return
                lines = (f'{time}.', f'Lap time {time}.', f'That was a {time}.')
            elif event['time'] < best - .049:
                gain = self.numbers.tenths(best - event['time']).speech
                lines = (f'{time}, best lap, {gain} quicker.', f'{time}. Your best, by {gain}.', f'Best lap so far, {time}.')
            elif tick.session == 'race':
                return
            elif event['time'] <= best + .049:
                lines = (f'{time}, right on your best.', f'{time}, matching your best.', f'{time}. Same as your best.')
            else:
                loss = self.numbers.tenths(event['time'] - best).speech
                lines = (f'{time}, {loss} off your best.', f'{time}. {loss} off.', f'{time}, {loss} down on your best.')
            self._say('C-35', f"lap_time:{event['lap']}", lines, evidence, tick, ctx)
            self._consistency(event, tick, ctx)
        elif kind == 'deleted' and not getattr(self,'original_penalties',False):
            place = self._corner_near(event.get('distance'))
            self._say('Q-09', f"deleted:{event['lap']}", (f"That lap's deleted, track limits{place}.",
                      f'Track limits{place}, lap deleted.', f'Lap deleted{place}. Track limits.'),
                      evidence, tick, ctx, this_lap=True)
        elif kind == 'pit_exit_cold':
            if event['tyres'] and event['brakes']:
                lines = ('Cold tyres and brakes. Build them up gently.',
                         'Tyres and brakes are cold, take it easy into the first braking zone.',
                         "Everything's cold, tyres and brakes. Careful for the first few corners.")
            elif event['tyres']:
                lines = ('Cold tyres, take it easy for the first lap.', 'Tyres are cold, build the temperature.',
                         'Cold tyres. Careful for the first few corners.')
            else:
                lines = ('Brakes are cold. Give them a few firm stops.', 'Cold brakes, warm them up.',
                         'Brakes are cold, careful into the first corner.')
            self._say('W-02', 'pit_exit_cold', lines, evidence, tick, ctx)
        elif kind == 'tyres_ready':
            self._say('W-05', 'tyres_ready', ('Tyres are up to temperature.', 'Tyres are in the window now.',
                      "Tyres are up to temperature. Push when you're ready."), evidence, tick, ctx)
        elif kind in ('tyres_hot', 'tyres_cooled', 'brakes_hot'):
            axle = event['axle']
            n = self._temperature(event.get('tyre_c') or event.get('brake_c'))
            tyres = 'Fronts' if axle == 'front' else 'Rears'
            if kind == 'tyres_hot':
                lines = (f'{tyres} are getting hot, {n}.', f'{axle} tyres are hot, {n} degrees.',
                         f'{tyres} running hot, {n}. Look after them.')
            elif kind == 'tyres_cooled':
                lines = (f'{tyres} have cooled, {n}. Work some heat back in.',
                         f'{axle} tyres are down to {n}, get some heat back in.', f'{tyres} have cooled off to {n}.')
            else:
                lines = (f'{axle} brakes are hot, {n}. Brake a little earlier to cool them.',
                         f'{axle} brakes running hot, {n}.', f'Hot {axle} brakes, {n}. Ease them for a lap.')
            self._say('M-02' if kind != 'brakes_hot' else 'M-10', f'{kind}:{axle}', lines, evidence, tick, ctx)
        elif kind == 'recon_corner':
            labels = event['labels']
            if len(labels) == 1:
                text = labels[0]
            else:
                plain = [re.sub(r'^turn ', '', l) for l in labels]
                text = ('turns ' + ', '.join(plain[:-1]) + ' and ' + plain[-1]) if all(l.startswith('turn ') for l in labels) \
                    else ', '.join(labels[:-1]) + ' and ' + labels[-1]
            text += '.' + (" That's the lap." if event['last'] else '')
            self._say('V-25', 'recon:' + str(round(event['apex'])), (text,), evidence, tick, ctx, ttl=4)
        elif kind == 'damage' and not getattr(self,'original_damage_reporting',False):
            parts, urgent = [], False
            for change in event['changes'][:2]:
                level, part = change['level'], change['part']
                urgent = urgent or level != 'minor'
                if part == 'aero':
                    parts.append({'minor': 'Aero damage, looks minor. Carry on.',
                                  'significant': "Aero damage. That'll cost some pace.",
                                  'heavy': 'Heavy aero damage. Box when you can.'}[level])
                elif part == 'suspension':
                    parts.append(f"Suspension damage, {change['wheel']}." + {
                        'minor': '', 'significant': ' Check the steering, it may pull.', 'heavy': ' Bring it in.'}[level])
                elif part == 'brake':
                    parts.append(f"Brake damage, {change['wheel']}. Brake a little earlier.")
                else:
                    parts.append({'minor': 'Engine took a knock. Keep an eye on it.'}.get(
                        level, 'Engine damage. Short-shift and look after it.'))
            self._say('M-23', 'damage:' + str(round(tick.t)), (' '.join(parts),),
                      {'changes': len(event['changes']), 'significant': urgent}, tick, ctx)
        elif kind == 'engine_hot' and not getattr(self, 'original_engine_monitor', False):
            n = self._temperature(event['temp_c'])
            lines = ((f"Water temperature's high, {n}. Get some clean air.", f'Water is running hot, {n}. Find some clean air.',
                      f'Water temp {n}. Pull out of the tow for a bit.') if event['what'] == 'water' else
                     (f"Oil's running hot, {n}. Back off a touch.", f'Oil temperature {n}, ease off a little.',
                      f'Oil is hot, {n}. Look after the engine.'))
            self._say('M-13', 'engine_hot:' + event['what'], lines, {'temp_c': event['temp_c']}, tick, ctx)
        elif kind == 'fuel_low' and not getattr(self,'original_fuel_monitor',False):
            whole = event['whole']
            if whole == 0:
                lines = ("Fuel's nearly gone, less than a lap left.", 'Less than a lap of fuel left.',
                         "You're on fumes, less than a lap of fuel.")
            else:
                n = integer_words(whole)
                laps = 'lap' if whole == 1 else 'laps'
                lines = (f'Fuel for about {n} {laps}.', f'About {n} {laps} of fuel left.', f'{n} {laps} of fuel left, roughly.')
            self._say('M-17', f'fuel_low:{whole}', lines, evidence, tick, ctx)

    def status(self):
        return {"driver": self.driver, "ticks": self.ticks,
                "context": {"session": self.context.session, "lap": self.context.lap,
                            "distance": self.context.distance, "active": self.context.active,
                            "reason": self.context.reason, "window_s": self.context.window_s,
                            "radio_busy": self.context.radio_busy} if self.context else None,
                "learned_laps": len(self.windows.laps) if self.windows else 0,
                "window_validation_pending": bool(self.windows and self.windows.needs_current_lap),
                "window_cache_error": self.window_cache_error,
                "diagnostics":dict(self.diagnostics),"inactive_reasons":dict(self.inactive_reasons),
                'gap_diagnostics':dict(self.gaps.diagnostics),
                'ahead_gap_diagnostics':dict(self.ahead_gaps.diagnostics),
                'fuel':self.fuel.status(self.context.t if self.context else 0,self.numbers),
                'race_length':self.race_length.status(self.context.t if self.context else 0),
                'corner_speed':self.corner_speed.status(),
                'braking':self.braking.status(),
                'sections':self.sections.status(),
                'offtrack':self.offtrack.status(),
                'laps':{'best':self.laps.best,'diagnostics':dict(self.laps.diagnostics)},
                'program':self.program.status() if self.program is not None else None,
                'apex':{**self.apex.status(),'map_reason':self.apex_store.reason if self.apex_store else 'matching_edge_map_missing',
                        'map_source':self.apex_store.source if self.apex_store else None,
                        'map_rejections':self.apex_store.rejected if self.apex_store else {}},
                "capabilities":self.capabilities(),
                "pending": len(self.radio.pending), "counts": dict(self.radio.log.counts)}
