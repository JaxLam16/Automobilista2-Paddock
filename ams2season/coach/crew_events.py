"""Original Crew Chief AMS2 penalty/flag events and current-state validation."""
from __future__ import annotations

import json
import re

from .crew_spotter import Spotter, ASSETS
from .model import finite

DEFAULTS=json.loads((ASSETS/'event_defaults.json').read_text(encoding='utf-8'))
COMMANDS={
    'DO_I_HAVE_A_PENALTY':('do i have a penalty',),
    'DO_I_STILL_HAVE_A_PENALTY':('do i still have a penalty',),
    'HAVE_I_SERVED_MY_PENALTY':('have i served my penalty',),
}
# Actual requests reachable in AMS2; other games' detailed causes are not invented.
FOLDERS=tuple('penalties/'+name for name in (
    'new_penalty_drivethrough','new_penalty_stopgo','penalty_three_laps_left','penalty_two_laps_left',
    'penalty_one_lap_left_drivethrough','penalty_one_lap_left_stopgo','penalty_disqualified',
    'pit_now_drive_through','pit_now_stop_go','penalty_not_served','penalty_served',
    'you_have_a_penalty','you_still_have_a_penalty','you_dont_have_a_penalty',
    'cut_track_in_race','lap_deleted','cut_track_in_prac_or_qual',
    'cut_track_race_1','cut_track_race_2','cut_track_race_3','cut_track_race_4',
    'cut_track_prac_or_qual_1','cut_track_prac_or_qual_2','cut_track_prac_or_qual_3','cut_track_prac_or_qual_4'))
FOLDERS+=('acknowledge/yes','acknowledge/no','mandatory_pit_stops/pit_this_lap')
FLAG_FOLDERS=tuple('flags/'+name for name in (
    'yellow_flag','double_yellow_flag','blue_flag','black_flag','white_flag'))


def command_for(text):
    words=' '.join(re.sub(r"[^a-z0-9 ]",'',str(text).casefold()).split())
    return next((cmd for cmd,phrases in COMMANDS.items() if words in phrases),None)


class Events(Spotter):
    host_script='events_host.ps1'
    host_name='events'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.settings=dict(DEFAULTS)
        if self.root is not None:
            try:
                from ..crew_chief import documents_folder
                values=json.loads((documents_folder()/'CrewChiefV4/Profiles/Paddock.json').read_text(encoding='utf-8-sig'))['userSettings']
                for key,default in DEFAULTS.items():
                    value=values.get(key,default)
                    if type(value) is type(default): self.settings[key]=value
            except (OSError,ValueError,TypeError,KeyError): pass
        self.started_at=None
        self.previous=None
        self.out_lap=False
        self.cuts=0
        self.valid_ids=set()
        self.acknowledged=[]
        self.last_payload=None
        self.state='waiting_for_telemetry'
        self.joined_with_penalty=False
        self.flag_state='waiting_for_telemetry'

    def start(self):
        # Parent snapshots settings when a workspace is supplied. Tests without a
        # root use the actual event defaults rather than the spotter settings file.
        if self.root is None:
            self.error='Original event host needs a private workspace for its settings snapshot.'
            return
        super().start()

    def reset(self):
        super().reset()
        if hasattr(self,'valid_ids'):
            self.valid_ids.clear()
            self.last_payload=None
            self.previous=None

    def valid_call(self, message_id):
        return str(message_id) in self.valid_ids

    def acknowledge(self,message_id):
        self.valid_ids.discard(str(message_id))
        self.acknowledged.append(str(message_id))

    def _send(self,payload):
        try:
            if payload['reset'] and (payload['drive_through'] or payload['stop_go']):
                self.joined_with_penalty=True
            result=self._request(payload)
            if result is None: return []
            if result.get('error'):
                self.error=result['error'];self.valid_ids.clear();return []
            self.valid_ids=set(result.get('valid',()))
            self._reset=False
            self.last_payload={**payload,'reset':False,'ack':[]}
            return [{**c,'id':('flags:' if c.get('source_event')=='FlagsMonitor_4.19.5.4' else 'penalties:')+c['id'],
                     'native_id':c['id']} for c in result.get('calls',())]
        except (OSError,ValueError) as exc:
            self.error=str(exc);self.reset();self.close();return []

    def feed(self,tick,player):
        age=finite(tick.local.get('local_sample_age_s'))
        schedule=tick.local.get('pit_schedule',player.pit_schedule if player else -1)
        race_state=tick.local.get('race_state',player.race_state if player else -1)
        speed=finite(tick.local.get('speed'))
        active=bool(tick.fresh and tick.game_state==2 and player is not None
                    and tick.viewed_slot==player.slot and race_state in (1,2,3)
                    and tick.session in ('practice','qualify','race','time_attack')
                    and age is not None and 0<=age<=.25
                    and player.pit in range(6) and speed is not None and player.distance is not None)
        penalties_available=bool(player is not None and schedule in range(8)
                                 and player.laps>=0 and player.sector in range(3))
        changed=tick.session_id!=self._session
        gap=self._last_t is not None and (tick.t<=self._last_t or tick.t-self._last_t>.5)
        if changed or gap: self.reset()
        if changed or self.started_at is None:
            self.started_at=tick.t;self.cuts=0;self.out_lap=False
        self._session,self._last_t=tick.session_id,tick.t
        if not active:
            self.flag_state='missing_or_inactive_telemetry'
            self.state='missing_or_inactive_telemetry';self.reset();return []
        before=self.previous
        new_lap=bool(before and (player.laps>before['laps'] or player.sector==0 and before['sector']==2))
        in_pits=player.pit!=0
        if before is None:
            self.out_lap=in_pits or player.laps==0
            self.joined_with_penalty=schedule in (5,6)
        elif in_pits and not before['pit']:
            self.out_lap=False
        elif in_pits and new_lap or not in_pits and before['pit']:
            self.out_lap=True
        elif not in_pits and new_lap:
            self.out_lap=False
        invalid=player.invalid or tick.local.get('local_lap_invalid') is True
        if before and penalties_available and before['penalties_available'] and not self.out_lap and before['lap_valid'] and invalid and not (tick.session=='race' and race_state==1):
            self.cuts+=1
        if schedule not in (5,6): self.joined_with_penalty=False
        if penalties_available and (before is None or not before['penalties_available']):
            self.joined_with_penalty=schedule in (5,6)
        yellow=tick.local.get('yellow_flag_state')
        phase='FullCourseYellow' if tick.session=='race' and yellow in (1,2,3,4,5,6,8) else 'Green'
        if tick.session=='race':
            if race_state==1: phase='Countdown'
            elif race_state==3: phase='Finished'
            elif phase=='Green' and any(c.position==1 and c.race_state==3 for c in tick.cars):
                phase='Checkered'
        else:
            duration=finite(tick.local.get('session_duration_s'))
            remaining=finite(tick.local.get('event_time_remaining_s'))
            if duration is not None and duration>0 and remaining is not None and remaining<=.2 and tick.t>self.started_at:
                phase='Checkered'
        # Original AMS2 mapper uses the authoritative local highest flag colour.
        # Older recordings only have the per-participant channel; retain that
        # explicit fallback, and never use a different driver's flag.
        colour=tick.local.get('flag_colour',player.flag_colour)
        self.flag_state='monitoring' if colour in range(12) else 'missing_flag_colour'
        just_green=bool(before and phase=='Green' and before['phase'] not in ('Green','Checkered','Finished'))
        self.previous={'laps':player.laps,'sector':player.sector,'pit':in_pits,'lap_valid':not invalid,'phase':phase,
                       'penalties_available':penalties_available}
        # The blue-flag repeat cap uses the nearest lapping car's identity. Only
        # supply class positions for a fully identified, complete observed class;
        # absent opponents leave Crew Chief's original unknown-opponent path.
        class_positions={}
        for cls in {c.car_class for c in tick.cars if c.car_class}:
            group=sorted((c for c in tick.cars if c.car_class==cls and c.position>0),key=lambda c:c.position)
            class_positions.update({c.identity:i+1 for i,c in enumerate(group)})
        opponents=[{'key':c.identity,'name':c.name,'position':c.position,
                    'class_position':class_positions[c.identity],'distance':c.distance,'speed':c.speed,
                    'pit':c.pit!=0,'entering_pits':c.pit==1}
                   for c in tick.cars if c.slot!=player.slot and c.identity in class_positions
                   and c.distance is not None and c.speed is not None and c.pit in range(6)]
        payload={'reset':self._reset,'t':tick.t,'running_s':tick.t-self.started_at,
                 'session':{'practice':'Practice','qualify':'Qualify','race':'Race','time_attack':'HotLap'}[tick.session],
                 'phase':phase,'laps':player.laps,'sector':player.sector+1,'lap_valid':not invalid,
                 'new_lap':new_lap,'pit':in_pits,'out_lap':self.out_lap,'speed':speed,'distance':player.distance,
                 'drive_through':schedule==5,'stop_go':schedule==6,'cuts':self.cuts,'ack':self.acknowledged,
                 'flag_colour':colour,'just_green':just_green,'position':player.position,
                 'class_position':class_positions.get(player.identity,1000),'track_length':tick.length,'opponents':opponents,
                 'penalties_available':penalties_available}
        self.acknowledged=[]
        self.state='monitoring' if self.ready.is_set() or self.host is not None else 'starting'
        if not penalties_available: self.state='missing_penalty_telemetry'
        return self._send(payload)

    def respond(self,command):
        if command not in COMMANDS or self.last_payload is None or not self.last_payload['penalties_available'] or self.joined_with_penalty: return []
        return self._send({**self.last_payload,'command':command,'ack':[]})
