"""Original installed English damage commands and sound folders. No estimates."""
import re

COMMANDS={
    'DAMAGE_REPORT':('damage report',"how's my car",'is my car ok'),
    'CAR_STATUS':('car status',),
    'STATUS':('full update','full status','update me'),
    'HOWS_MY_AERO':("how's my aero","how's my bodywork"),
    'HOWS_MY_BRAKES':("how's my brakes",'how are my brakes'),
    'HOWS_MY_ENGINE':("how's my engine",),
    'HOWS_MY_SUSPENSION':("how's my suspension",),
    'HOWS_MY_TRANSMISSION':("how's my transmission","how's my gearbox"),
}
I_AM_OK=('yeah','yes','fine',"I'm OK","I'm fine","yes I'm fine","yeah I'm fine")
FOLDERS=tuple('damage_reporting/'+name for name in (
    'damage','minor_transmission_damage','minor_engine_damage','minor_aero_damage',
    'minor_aero_damage_general','minor_suspension_damage','minor_suspension_damage_general',
    'minor_brake_damage','severe_transmission_damage','severe_engine_damage','severe_aero_damage',
    'severe_brake_damage','severe_suspension_damage','busted_transmission','busted_engine',
    'busted_suspension','busted_brakes','no_transmission_damage','no_engine_damage',
    'no_aero_damage','no_suspension_damage','no_brake_damage','trivial_aero_damage',
    'trivial_aero_damage_general','missing_wheel','left_front_puncture','right_front_puncture',
    'left_rear_puncture','right_rear_puncture','no_damage','rolling','stopped_upside_down',
    'are_you_ok_first_try','are_you_ok_second_try','are_you_ok_third_try',
    'acknowledge_driver_is_ok','acknowledge_driver_is_ok_not_understood',
    'acknowledge_driver_is_ok_no_speech'))

def command_for(text):
    clean=lambda s:' '.join(re.sub(r'[^a-z0-9 ]','',str(s).casefold()).split())
    return next((key for key,phrases in COMMANDS.items() if clean(text) in map(clean,phrases)),None)

def clearly_ok(text):
    # Original ResultContains lowercases and uses equality, then substring matching.
    return any(phrase.lower() in str(text).lower() for phrase in I_AM_OK)
