"""Every adjustable setting the engineer can recommend (all the red-arrow items in AMS2's garage), grouped
into the nine status categories. Ticks are always relative: AMS2 doesn't share the setup, so the engineer
tracks it from the default baseline through the changes you confirm."""
from __future__ import annotations

CATEGORIES = [
    ("pit_strategy", "Pit strategy"), ("gearing", "Gearing"), ("ground_clearance", "Ground clearance"),
    ("tyre_contact", "Tyre contact"), ("chassis_balance", "Chassis balance"), ("aero_balance", "Aero balance"),
    ("downforce", "Downforce level"), ("braking_traction", "Braking & traction"), ("thermals", "Thermals & reliability"),
]
CAT_LABEL = dict(CATEGORIES)
CORNER = {"fl": "Front left", "fr": "Front right", "rl": "Rear left", "rr": "Rear right"}
UP_DOWN = {
    "more": ("Increase", "Decrease"), "stiff": ("Stiffen", "Soften"), "height": ("Raise", "Lower"),
    "camber": ("More negative camber", "Less negative camber"), "aero": ("Add", "Remove"),
    "bias": ("Move forward", "Move rearward"), "open": ("Open", "Close"), "gear": ("Shorten", "Lengthen"),
    "lock": ("Add lock", "Reduce lock"), "toe": ("More toe-in", "Less toe-in (towards toe-out)"),
}
# What the number on AMS2's setup screen does, for each direction: (positive ticks, negative ticks).
# Where the meaning of a higher number varies between cars, it says so rather than guess.
GARAGE = {
    "more": ("the number goes up", "the number goes down"),
    "stiff": ("the number goes up (higher = stiffer)", "the number goes down (lower = softer)"),
    "height": ("the number goes up (mm)", "the number goes down (mm)"),
    "camber": ("the number goes further below zero, e.g. -3.5° → -3.7°", "the number moves towards zero, e.g. -3.5° → -3.3°"),
    "aero": ("the number goes up", "the number goes down"),
    "bias": ("the front figure goes up, e.g. 55.0/45.0 → 55.5/44.5", "the front figure goes down, e.g. 55.0/45.0 → 54.5/45.5"),
    "open": ("the % goes up", "the % goes down"),
    "gear": ("the ratio number goes up, e.g. 3.525 → 3.600 (higher ratio = shorter gearing)", "the ratio number goes down, e.g. 3.525 → 3.450 (lower ratio = longer gearing)"),
    "lock": ("the number goes up (more locking)", "the number goes down (less locking)"),
    "toe": ("the Toe-In Angle goes up, e.g. 0.2° → 0.3°", "the Toe-In Angle goes down, e.g. 0.2° → 0.1° (below zero is toe-out)"),
}
GARAGE_CHECK = {  # settings whose numbering differs between cars
    "traction_control": "on most cars a higher number means more TC; check the description in the garage",
    "abs": "on most cars a higher number means more ABS; check the description in the garage",
    "engine_braking": "on some cars a higher number means more engine braking, on others less; check the description in the garage",
}


def _s(key, label, cat, tab, verbs="more", analysed=True, also=()):
    """`also`: other categories the setting serves (the wings set both aero balance and downforce level)."""
    return {"key": key, "label": label, "category": cat, "tab": tab, "verbs": verbs, "analysed": analysed, "also": list(also)}


SETTINGS = []
for w, nm in CORNER.items():
    SETTINGS += [_s(f"pressure_{w}", f"{nm} tyre pressure", "tyre_contact", "Tyres / Brakes / Chassis"),
                 _s(f"camber_{w}", f"{nm} camber", "tyre_contact", "Suspension", "camber"),
                 _s(f"ride_height_{w}", f"{nm} ride height", "ground_clearance", "Suspension", "height"),
                 _s(f"spring_{w}", f"{nm} spring rate", "chassis_balance", "Suspension", "stiff"),
                 _s(f"bump_stop_{w}", f"{nm} bump stop", "ground_clearance", "Suspension"),
                 _s(f"slow_bump_{w}", f"{nm} slow bump", "chassis_balance", "Suspension", "stiff", analysed=False),
                 _s(f"slow_rebound_{w}", f"{nm} slow rebound", "chassis_balance", "Suspension", "stiff", analysed=False),
                 _s(f"fast_bump_{w}", f"{nm} fast bump", "chassis_balance", "Suspension", "stiff"),
                 _s(f"fast_rebound_{w}", f"{nm} fast rebound", "chassis_balance", "Suspension", "stiff", analysed=False)]
    SETTINGS.append(_s(f"compound_{w}", f"{nm} tyre compound", "tyre_contact", "Tyres / Brakes / Chassis", analysed=False))
SETTINGS += [
    _s("caster_fl", "Front left caster", "chassis_balance", "Suspension", analysed=False),
    _s("caster_fr", "Front right caster", "chassis_balance", "Suspension", analysed=False),
    _s("toe_front", "Front toe", "tyre_contact", "Suspension", "toe", analysed=False),
    _s("toe_rear", "Rear toe", "chassis_balance", "Suspension", "toe"),
    _s("arb_front", "Front anti-roll bar", "chassis_balance", "Suspension", "stiff"),
    _s("arb_rear", "Rear anti-roll bar", "chassis_balance", "Suspension", "stiff"),
    _s("third_front", "Front 3rd spring", "ground_clearance", "Suspension", "stiff", analysed=False),
    _s("third_rear", "Rear 3rd spring", "ground_clearance", "Suspension", "stiff", analysed=False),
    _s("steering_lock", "Steering lock", "chassis_balance", "Suspension"),
    _s("brake_pressure", "Brake pressure", "braking_traction", "Tyres / Brakes / Chassis"),
    _s("brake_bias", "Brake bias", "braking_traction", "Tyres / Brakes / Chassis", "bias"),
    _s("duct_front", "Front brake duct", "thermals", "Tyres / Brakes / Chassis", "open"),
    _s("duct_rear", "Rear brake duct", "thermals", "Tyres / Brakes / Chassis", "open"),
    _s("downforce_front", "Front downforce", "aero_balance", "Tyres / Brakes / Chassis", "aero", also=("downforce",)),
    _s("downforce_rear", "Rear downforce", "aero_balance", "Tyres / Brakes / Chassis", "aero", also=("downforce",)),
    _s("lateral_weight", "Lateral weight bias", "chassis_balance", "Tyres / Brakes / Chassis", analysed=False),
    _s("weight_jacker", "Weight jacker", "chassis_balance", "Tyres / Brakes / Chassis", analysed=False),
    _s("fuel", "Fuel", "pit_strategy", "Drivetrain"),
    _s("boost", "Boost pressure", "thermals", "Drivetrain", analysed=False),
    _s("radiator", "Radiator opening", "thermals", "Drivetrain", "open"),
    _s("engine_braking", "Engine braking", "braking_traction", "Drivetrain"),
    _s("traction_control", "Traction control", "braking_traction", "Drivetrain"),
    _s("abs", "Anti-lock brakes", "braking_traction", "Drivetrain"),
    _s("final_drive", "Final drive", "gearing", "Drivetrain", "gear"),
    *[_s(f"gear_{i}", f"{i}{'st' if i == 1 else 'nd' if i == 2 else 'rd' if i == 3 else 'th'} gear", "gearing", "Drivetrain", "gear", analysed=False) for i in range(1, 9)],
    _s("rear_diff_preload", "Rear diff preload", "braking_traction", "Drivetrain", "lock", analysed=False),
    _s("rear_diff_clutches", "Rear diff clutches", "braking_traction", "Drivetrain", "lock"),
    _s("rear_diff_power", "Rear diff power ramp", "braking_traction", "Drivetrain", "lock", analysed=False),
    _s("rear_diff_coast", "Rear diff coast ramp", "braking_traction", "Drivetrain", "lock", analysed=False),
]
BY_KEY = {s["key"]: s for s in SETTINGS}


def garage_hint(key: str, ticks: int) -> str:
    """What the change looks like on AMS2's setup screen: which way the number moves."""
    s = BY_KEY[key]
    if key in GARAGE_CHECK:
        return GARAGE_CHECK[key]
    up, down = GARAGE.get(s["verbs"], ("the number goes up", "the number goes down"))
    return up if ticks > 0 else down


def action_text(key: str, ticks: int) -> str:
    s = BY_KEY[key]
    up, down = UP_DOWN[s["verbs"]]
    n = abs(int(ticks))
    return f"{up if ticks > 0 else down} by {n} tick{'s' if n != 1 else ''}"
