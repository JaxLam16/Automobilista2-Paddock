"""Byte-preserving editing of documented Madness physics values.

This is a deliberately bounded decoder, not a replacement physics simulation.
Signatures are data-format facts from JDougNY/GvsE's translations and the
RangeyRover engine editor. No external editor code is included.
"""
from __future__ import annotations

import html
import math
import re
import struct
from dataclasses import dataclass


@dataclass
class Parameter:
    id: str
    label: str
    group: str
    offset: int
    fmt: str
    value: float | int
    unit: str = ''
    minimum: float = -1e9
    maximum: float = 1e9
    note: str = ''
    promotable: bool = False
    record_start: int = -1
    record_end: int = -1

    def public(self):
        return {k: getattr(self, k) for k in ('id', 'label', 'group', 'value', 'unit', 'minimum', 'maximum', 'note')} | {
            'integer': self.fmt != 'f' and not self.promotable, 'editable': self.offset >= 0,
            'reason': '' if self.offset >= 0 else 'Zero-default encoding has no stored value; changing it would resize the binary file.'}


def crd_properties(raw: bytes) -> dict[str, str]:
    """Some mod CRDs have a stray closing tag; preserve it, read prop tags only."""
    result = {}
    for tag in re.findall(rb'<prop\b[^>]*>', raw, re.I):
        attrs = {k.decode().lower(): html.unescape(v.decode('utf-8'))
                 for k, _, v in re.findall(rb'([\w]+)\s*=\s*(["\'])(.*?)\2', tag, re.S)}
        if 'name' in attrs and 'data' in attrs:
            if attrs['name'] in result:
                raise ValueError('Duplicate CRD property: ' + attrs['name'])
            result[attrs['name']] = attrs['data']
    return result


def change_crd(raw: bytes, changes: dict[str, str]) -> bytes:
    properties = crd_properties(raw)
    if not set(changes) <= properties.keys():
        raise ValueError('The CRD is missing a required class property.')
    def replace(match):
        tag = match.group()
        attrs = dict((k.decode().lower(), html.unescape(v.decode('utf-8')))
                     for k, _, v in re.findall(rb'([\w]+)\s*=\s*(["\'])(.*?)\2', tag, re.S))
        name = attrs.get('name')
        if name not in changes:
            return tag
        value = html.escape(str(changes[name]), quote=True).encode('utf-8')
        return re.sub(rb'(\bdata\s*=\s*)(["\'])(.*?)\2',
                      lambda m: m[1] + m[2] + value + m[2], tag, count=1, flags=re.I | re.S)
    out = re.sub(rb'<prop\b[^>]*>', replace, raw, flags=re.I)
    if any(crd_properties(out).get(k) != str(v) for k, v in changes.items()):
        raise ValueError('Could not verify the changed CRD.')
    return out


def shcb_region(raw: bytes) -> tuple[int, int]:
    if len(raw) < 28 or raw[:4] != b'ShCB' or struct.unpack_from('<I', raw, 8)[0] != len(raw):
        raise ValueError('Unrecognized or truncated ShCB physics file.')
    version = struct.unpack_from('<I', raw, 12)[0]
    if version not in (1, 2) or raw[16:20] != b'\xba\xba\x10\x10':
        raise ValueError('This ShCB physics version is not supported.')
    length, start = struct.unpack_from('<II', raw, 20)
    end = start + length
    if start < (40 if version == 2 else 28) or not start <= end <= len(raw):
        raise ValueError('Invalid ShCB data section.')
    if version == 2 and (struct.unpack_from('<I', raw, 36)[0] != end or
                         struct.unpack_from('<I', raw, 32)[0] + end != len(raw)):
        raise ValueError('Invalid ShCB footer boundaries.')
    return start, end


# Compound type codes: explicitly documented layouts, never inferred floats.
_LAYOUTS = {b'\x01': 'B', b'\x11': 'i', b'\x21': 'f', b'\x02': 'BB',
            b'\x52': 'ii', b'\x82': 'Bf', b'\xa2': 'ff',
            b'\x03\x00': 'BBB', b'\x03\x02': 'BBf', b'\x13\x00': 'iBB',
            b'\x23\x00': 'fBB', b'\x23\x02': 'fBf', b'\x83\x00': 'BfB',
            b'\x83\x02': 'Bff', b'\xa3\x00': 'ffB', b'\xa3\x02': 'fff',
            b'\x53\x00': 'iiB', b'\x53\x01': 'iii', b'\x63\x00': 'fiB'}

# Only documented real-valued CDF properties can widen their numeric encoding.
# Counts, switches, settings, engine RPM and mass retain their stored type.
_REAL_CDF = {'fw_drag', 'fw_lift', 'rw_drag', 'rw_lift', 'diffuser',
             'diffuser_front_height', 'diffuser_rake', 'diffuser_limits',
             'diffuser_stall', 'diffuser_sideways', 'fw_max_height',
             'fw_lift_height', 'fw_sideways', 'rw_peak_yaw', 'rw_sideways',
             'body_drag', 'body_height_drag', 'body_rake_drag', 'body_max_height',
             'fw_range', 'rw_range', 'spring_range', 'ride_height',
             'slow_bump', 'fast_bump', 'slow_rebound', 'fast_rebound',
             'front_arb_range', 'rear_arb_range', 'bumpstop_spring', 'bumpstop_rising'}

_VECTOR_KEYS = {'diffuser', 'diffuser_rake', 'diffuser_limits', 'diffuser_stall', 'rw_peak_yaw'}


def _real_component(kind, key, index, arity):
    return kind == 'cdf' and key in _REAL_CDF and (arity < 3 or index < 2 or key in _VECTOR_KEYS or key.endswith(('_lift', '_drag')))


def _occurrences(raw, needle, start, end):
    while (pos := raw.find(needle, start, end)) >= 0:
        yield pos
        start = pos + len(needle)


def _fields(raw: bytes, kind: str, definitions: list[tuple]) -> list[Parameter]:
    start, end = shcb_region(raw)
    result = []
    for key, marker, label, group, unit, low, high in definitions:
        found = []
        for p in _occurrences(raw, bytes.fromhex(marker), start + 1, end):
            lead = raw[p - 1]
            if lead == 0x28:
                # Scalar zero/default records have no payload. Keep them visible
                # for complete model comparison; they cannot be widened here.
                found.append((p, 'B', -1, (0,)))
                continue
            if lead in (0x20, 0x21, 0x22):
                fmt, offset = {0x20: 'B', 0x21: 'i', 0x22: 'f'}[lead], p + 4
            elif lead == 0x24:
                offset = p + 4
                layout = next(((code, fmt) for code, fmt in _LAYOUTS.items()
                               if raw.startswith(code, offset)), None)
                if layout is None:
                    continue
                code, fmt = layout
                offset += len(code)
            else:
                continue  # zero/default/unknown encoding is not writable
            if offset + struct.calcsize('<' + fmt) > end:
                continue
            values = struct.unpack_from('<' + fmt, raw, offset)
            if any(not math.isfinite(v) or abs(v) > 1e12 for v in values):
                continue
            found.append((p, fmt, offset, values))
        for occurrence, (p, fmt, offset, values) in enumerate(sorted(found)):
            # Repeated corner properties keep stable, semantic IDs, never offsets in presets.
            corner = _corner(raw, p, start) if group in ('Brakes', 'Suspension') else ''
            suffix = (' · ' + corner) if corner else (' · block ' + str(occurrence + 1) if len(found) > 1 else '')
            record_end = offset + struct.calcsize('<' + fmt) if offset >= 0 else p + 4
            for index, (code, value) in enumerate(zip(fmt, values)):
                component = (' · ' + _component(key, index)) if len(fmt) > 1 else ''
                minimum, maximum = low, high
                real = _real_component(kind, key, index, len(fmt))
                if offset < 0:
                    minimum, maximum = 0, 0
                elif code == 'B' and not real:
                    minimum, maximum = (max(0, low), min(255, high)) if len(fmt) == 1 else (0, 255)
                elif code == 'i' and not real: minimum, maximum = max(low, -2147483648), min(high, 2147483647)
                # Include unusual installed values for inspection without inventing constraints.
                note = ('Documented zero-default encoding; no numeric bytes are present.' if offset < 0 else
                        'Documented coefficient tuple.' if key in _VECTOR_KEYS or key.endswith(('_lift', '_drag')) else
                        'Documented file parameter; range components are base, step and setting count.' if len(fmt) > 1 else '')
                result.append(Parameter(f'{kind}.{key}.{occurrence}.{index}', label + suffix + component,
                                        group, offset, code, value, unit, minimum, maximum, note,
                                        real, p - 1, record_end))
                if offset >= 0: offset += struct.calcsize('<' + code)
    return sorted(result, key=lambda p: p.offset)


def _corner(raw, pos, start):
    markers = {'e07d16e29f': 'Front left', 'e0d6537908': 'Front right',
               'e0bf9f5ba2': 'Rear left', 'e0cff2c932': 'Rear right'}
    preceding = [(raw.rfind(bytes.fromhex(m), start, pos), name) for m, name in markers.items()]
    found = max(preceding)
    return found[1] if found[0] >= 0 else ''


def _component(key, index):
    if key.endswith(('_lift', '_drag')): return ('constant', 'linear', 'quadratic')[index]
    if key == 'inertia': return ('X', 'Y', 'Z')[index]
    if key == 'diffuser': return ('base lift', 'rear-height linear', 'rear-height quadratic')[index]
    if key == 'diffuser_rake': return ('optimum rake', 'linear', 'quadratic')[index]
    if key == 'diffuser_limits': return ('minimum height', 'maximum height', 'maximum rake difference')[index]
    if key == 'diffuser_stall': return ('first', 'second')[index]
    if key in ('idle', 'launch_rpm', 'lifetime_rpm', 'oil_water', 'radiator_cooling'):
        return str(index + 1)
    return ('base', 'step', 'count')[index]


# Labels/units describe encoded values, not simulated handling or lap-time scores.
_CDF = [
    ('mass', '670b57ab', 'Mass', 'Chassis', 'kg', 100, 10000),
    ('power_multiplier', 'a3bf1e60', 'Power multiplier', 'Engine', '×', 0.05, 10),
    ('inertia', 'bbb39f0b', 'Body inertia', 'Chassis', 'kg·m²', 0.001, 1e7),
    ('cg_height', '1824eaa8', 'Centre of gravity height', 'Chassis', 'm', 0.01, 5),
    ('cg_rear', 'beba677b', 'Rear weight share range', 'Chassis', 'share', 0, 1),
    ('cg_rear_setting', 'd44c53c4', 'Rear weight share setting', 'Chassis', 'index', 0, 255),
    ('fuel_range', '19389974', 'Fuel capacity range', 'Fuel', 'L', 0, 5000),
    ('fw_range', 'ad3c2013', 'Front wing range', 'Aero', '', -1e4, 1e4),
    ('fw_setting', '06a31f94', 'Front wing default setting', 'Aero', 'index', 0, 255),
    ('fw_drag', '2cfb70da', 'Front wing drag polynomial', 'Aero', 'coefficient', -100, 100),
    ('fw_lift', '23ec212a', 'Front wing lift polynomial', 'Aero', 'coefficient', -100, 100),
    ('rw_range', '15765486', 'Rear wing range', 'Aero', '', -1e4, 1e4),
    ('rw_setting', '8a98eb35', 'Rear wing default setting', 'Aero', 'index', 0, 255),
    ('rw_drag', '67dcb6b3', 'Rear wing drag polynomial', 'Aero', 'coefficient', -100, 100),
    ('rw_lift', '83d385b9', 'Rear wing lift polynomial', 'Aero', 'coefficient', -100, 100),
    ('fw_max_height', '09a852d9', 'Front wing maximum height', 'Aero', 'm', 0, 5),
    ('fw_lift_height', '06f458ac', 'Front wing lift / height', 'Aero', 'coefficient', -100, 100),
    ('fw_sideways', '96d38a17', 'Front wing lift / sideways motion', 'Aero', 'coefficient', -100, 100),
    ('rw_sideways', '7a8f77c8', 'Rear wing lift / sideways motion', 'Aero', 'coefficient', -100, 100),
    ('rw_peak_yaw', '152e2037', 'Rear wing yaw response', 'Aero', 'file units', -100, 100),
    ('body_drag', '3363edfd', 'Body base drag', 'Aero', 'coefficient', 0, 100),
    ('body_height_drag', '67caa092', 'Body drag / average ride height', 'Aero', 'coefficient', -100, 100),
    ('body_rake_drag', '1f13c185', 'Body drag / rake', 'Aero', 'coefficient', -100, 100),
    ('body_max_height', '56e0a3ab', 'Body maximum aero height', 'Aero', 'm', 0, 5),
    ('diffuser', 'be0f2899', 'Diffuser base values', 'Aero', 'file units', -10000, 10000),
    ('diffuser_front_height', '47d0b1de', 'Diffuser front-height effect', 'Aero', 'coefficient', -10000, 10000),
    ('diffuser_rake', '20b98dff', 'Diffuser rake response', 'Aero', 'file units', -10000, 10000),
    ('diffuser_limits', 'ff5946c8', 'Diffuser operating limits', 'Aero', 'm', 0, 5),
    ('diffuser_stall', 'e0a125de', 'Diffuser stall response', 'Aero', 'file units', -10000, 10000),
    ('diffuser_sideways', 'e1763224', 'Diffuser sideways response', 'Aero', 'coefficient', -10000, 10000),
    ('clutch_torque', '2e33db70', 'Clutch torque capacity', 'Drivetrain', 'Nm', 1, 100000),
    ('upshift_delay', '67f7ad20', 'Upshift delay', 'Drivetrain', 's', 0, 10),
    ('downshift_delay', '0750af26', 'Downshift delay', 'Drivetrain', 's', 0, 10),
    ('final_setting', 'c1ebdc28', 'Final drive default option', 'Gearing', 'index', 0, 255),
    ('forward_gears', 'ff0c2207', 'Forward gear count', 'Gearing', '', 1, 10),
    ('brake_torque', '4ba4817a', 'Brake torque', 'Brakes', 'Nm', 1, 100000),
    ('brake_heating', '6ea60dfb', 'Brake heating', 'Brakes', 'coefficient', 0, 100),
    ('brake_cooling', '1cd55c78', 'Brake cooling', 'Brakes', 'file units', 0, 100),
    ('spring_based_arb', '26e982b6', 'Spring-based anti-roll bars', 'Roll control', '0 / 1', 0, 1),
    ('front_arb_range', 'e5b9a9d6', 'Front anti-roll bar range', 'Roll control', 'file units', 0, 1e8),
    ('front_arb_setting', '7fc758d5', 'Front anti-roll bar default setting', 'Roll control', 'index', 0, 255),
    ('rear_arb_range', '66001e25', 'Rear anti-roll bar range', 'Roll control', 'file units', 0, 1e8),
    ('rear_arb_setting', '0478e991', 'Rear anti-roll bar default setting', 'Roll control', 'index', 0, 255),
    ('bump_travel', 'b3d821f7', 'Bump travel coordinate', 'Suspension', 'm', -5, 5),
    ('rebound_travel', '177b8a89', 'Rebound travel coordinate', 'Suspension', 'm', -5, 5),
    ('bumpstop_spring', '7fc6f841', 'Bump-stop initial spring rate', 'Suspension', 'N/m', 0, 1e10),
    ('bumpstop_rising', 'cb91f163', 'Bump-stop rising spring coefficient', 'Suspension', 'file units', 0, 1e12),
    ('spring_multiplier', '44495d88', 'Spring multiplier', 'Suspension', '×', 0.01, 100),
    ('damper_multiplier', '51374153', 'Damper multiplier', 'Suspension', '×', 0.01, 100),
    ('spring_range', 'a5123d0d', 'Spring range', 'Suspension', 'N/m', -1e7, 1e7),
    ('spring_setting', 'ceaa7a97', 'Spring default setting', 'Suspension', 'index', 0, 255),
    ('ride_height', 'd7c60d7a', 'Ride height range', 'Suspension', 'm', -5, 5),
    ('ride_height_setting', '6d049405', 'Ride height default setting', 'Suspension', 'index', 0, 255),
    ('slow_bump', '0c43d9d0', 'Slow bump range', 'Suspension', 'N·s/m', -1e7, 1e7),
    ('slow_bump_setting', 'd19e2c0a', 'Slow bump default setting', 'Suspension', 'index', 0, 255),
    ('fast_bump', '3089ec3d', 'Fast bump range', 'Suspension', 'N·s/m', -1e7, 1e7),
    ('fast_bump_setting', '38382587', 'Fast bump default setting', 'Suspension', 'index', 0, 255),
    ('slow_rebound', 'bcc0a291', 'Slow rebound range', 'Suspension', 'N·s/m', -1e7, 1e7),
    ('slow_rebound_setting', '2273d781', 'Slow rebound default setting', 'Suspension', 'index', 0, 255),
    ('fast_rebound', 'bc6d0ef7', 'Fast rebound range', 'Suspension', 'N·s/m', -1e7, 1e7),
    ('fast_rebound_setting', 'b8b0022e', 'Fast rebound default setting', 'Suspension', 'index', 0, 255),
    ('abs', 'bc1266e0', 'Authentic ABS enabled', 'Assists', '0 / 1', 0, 1),
    ('tc', 'bc907f88', 'Authentic traction control enabled', 'Assists', '0 / 1', 0, 1),
]
for number, marker in enumerate(('f4cc2f1d', '8d69c2da', 'c02593c3', '7892b75a', '784e4836', '5f2ba9ee', '49ee13f6'), 1):
    _CDF.append((f'gear{number}_setting', marker, f'Gear {number} default option', 'Gearing', 'index', 0, 255))

_EDF = [
    ('fuel_consumption', '4ae2dd6c', 'Fuel consumption coefficient', 'Fuel', 'file units', 0, 1),
    ('engine_inertia', '4665ae87', 'Engine inertia', 'Engine', 'kg·m²', 0.001, 100),
    ('idle', '4d239754', 'Idle RPM range', 'Engine', 'rpm', 0, 30000),
    ('launch_rpm', '7902b6bd', 'Launch RPM range', 'Engine', 'rpm', 0, 30000),
    ('rev_limit', 'dea72eb7', 'Rev limiter range', 'Engine', 'rpm', 0, 30000),
    ('rev_setting', 'a55cc1c4', 'Rev limiter default setting', 'Engine', 'index', 0, 255),
    ('engine_braking', 'bf847cf1', 'Engine braking map range', 'Engine', '', -10000, 10000),
    ('oil_temp', 'afd78add', 'Optimum oil temperature', 'Cooling', '°C', 0, 300),
    ('combustion_heat', '54106db1', 'Combustion heat', 'Cooling', 'file units', 0, 10000),
    ('speed_heat', 'f6e39fd9', 'Engine speed heat', 'Cooling', 'file units', 0, 10000),
    ('oil_cooling', 'b30f25fc', 'Oil minimum cooling', 'Cooling', 'file units', 0, 1000),
    ('oil_water', 'a700d23a', 'Oil / water heat transfer', 'Cooling', 'file units', 0, 1000),
    ('water_cooling', '67171586', 'Water minimum cooling', 'Cooling', 'file units', 0, 1000),
    ('radiator_cooling', '6ada2b3a', 'Radiator cooling', 'Cooling', 'file units', 0, 1000),
    ('lifetime_rpm', 'd39464af', 'Engine lifetime RPM', 'Reliability', 'rpm', 0, 30000),
    ('lifetime', 'f75f822b', 'Engine lifetime average', 'Reliability', 'file units', 1, 1e12),
    ('displacement', '92c7cd7c', 'Displacement', 'Engine', 'L', 0.05, 100),
    ('restrictor', 'fc89e89c', 'Air restrictor range', 'Engine', 'file units', 0, 100),
    ('restrictor_setting', 'c5b408fe', 'Air restrictor default setting', 'Engine', 'index', 0, 255),
    ('boost_range', 'd774451a', 'Boost range', 'Engine', 'file units', 0, 100),
    ('boost_setting', 'ca2fd134', 'Boost default setting', 'Engine', 'index', 0, 255),
]


def torque_tables(raw: bytes) -> list[list[Parameter]]:
    start, end = shcb_region(raw)
    base = bytes.fromhex('248b0ab771')
    signatures = [(base + bytes.fromhex(code), fmt, indexes) for code, fmt, indexes in (
        ('8302', 'Bff', (None, 1, 2)), ('0302', 'BBf', (None, 2, None)),
        ('9302', 'iff', (0, 1, 2)), ('a302', 'fff', (0, 1, 2)), ('9300', 'ifB', (0, 1, None)))]
    tables, used = [], start
    positions = sorted({p for sig, _, _ in signatures for p in _occurrences(raw, sig, start, end)})
    for pos in positions:
        if pos < used:
            continue
        fields, q, last_rpm, row = [], pos, -1, 0
        while q < end:
            variant = next(((sig, fmt, indexes) for sig, fmt, indexes in signatures if raw.startswith(sig, q)), None)
            if variant is None:
                break
            sig, fmt, (rpm_idx, comp_idx, torque_idx) = variant
            offset = q + len(sig)
            if offset + struct.calcsize('<' + fmt) > end:
                break
            values = struct.unpack_from('<' + fmt, raw, offset)
            rpm = values[rpm_idx] if rpm_idx is not None else 0
            if not math.isfinite(rpm) or not 0 <= rpm <= 30000 or rpm <= last_rpm:
                break
            if any(not math.isfinite(v) or abs(v) > 100000 for v in values):
                break
            table = len(tables)
            offsets = [offset + struct.calcsize('<' + fmt[:i]) for i in range(len(fmt))]
            for idx, key, label, low, high in ((comp_idx, 'compression', 'Engine braking / compression', -10000, 10000),
                                             (torque_idx, 'torque', 'Torque', -10000, 20000)):
                if idx is not None:
                    fields.append(Parameter(f'edf.{key}.{table}.{row}', f'{label} · {rpm:g} rpm · map {table + 1}',
                                            'Torque curves', offsets[idx], 'f', values[idx], 'Nm', low, high))
            # RPM is deliberately read-only: changing it can break row ordering.
            fields.append(Parameter(f'edf.rpm.{table}.{row}', f'RPM · map {table + 1}', 'RPM',
                                    offsets[rpm_idx] if rpm_idx is not None else -1,
                                    fmt[rpm_idx] if rpm_idx is not None else 'B', rpm, 'rpm', rpm, rpm))
            row += 1
            last_rpm = rpm
            q = offset + struct.calcsize('<' + fmt)
        if row >= 2:
            tables.append(fields)
            used = q
    return tables


def gearbox_fields(raw: bytes) -> list[Parameter]:
    start, end = shcb_region(raw)
    if not raw.startswith(bytes.fromhex('6088de240f'), start):
        raise ValueError('Unrecognized gearbox ratio table.')
    boundary = raw.find(bytes.fromhex('e09765b7af'), start, end)
    if boundary < 0:
        raise ValueError('The gearbox final-drive section is missing.')
    result = []
    for key, a, b, marker in [('gear', start, boundary, '249d58f96402'),
                             ('bevel', boundary, end, '243c5bef6202'),
                             ('final', boundary, end, '249d58f96402')]:
        for option, p in enumerate(_occurrences(raw, bytes.fromhex(marker), a, b)):
            if p + 8 > b:
                raise ValueError('Truncated gearbox ratio pair.')
            for cog, label in enumerate(('driver teeth', 'driven teeth')):
                value = raw[p + 6 + cog]
                if not value:
                    raise ValueError('A gearbox ratio has zero teeth.')
                result.append(Parameter(f'gdf.{key}.{option}.{cog}', f'{key.title()} option {option + 1} · {label}',
                                        'Gearing', p + 6 + cog, 'B', value, 'teeth', 1, 255,
                                        'Ratio = driven teeth / driver teeth. These are options; chassis defaults choose the active ratios.'))
    return result


def decode(kind: str, raw: bytes) -> list[Parameter]:
    if kind == 'cdf':
        fields = _fields(raw, kind, _CDF)
        if len({p.id for p in fields}) != len(fields): raise ValueError('Ambiguous repeated chassis parameter encoding.')
        return fields
    if kind == 'edf':
        return sorted(_fields(raw, kind, _EDF) + [p for table in torque_tables(raw) for p in table], key=lambda p: p.offset)
    if kind == 'gdf': return gearbox_fields(raw)
    return []


def edit(kind: str, raw: bytes, changes: dict[str, float]) -> bytes:
    fields = {p.id: p for p in decode(kind, raw) if p.group != 'RPM' and p.offset >= 0}
    if not set(changes) <= fields.keys():
        raise ValueError('An edited parameter is unavailable in this physics file.')
    for key, v in changes.items():
        p = fields[key]
        if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v):
            raise ValueError('Enter a finite number for ' + p.label + '.')
        if not p.minimum <= v <= p.maximum or (p.fmt != 'f' and not p.promotable and int(v) != v):
            raise ValueError(f'{p.label}: enter {"an integer" if p.fmt != "f" else "a value"} from {p.minimum:g} to {p.maximum:g}.')
    out = bytearray(raw)
    promoted = set()
    for key, v in changes.items():
        p = fields[key]
        fits = p.fmt == 'f' or (int(v) == v and
               (0 <= v <= 255 if p.fmt == 'B' else -2147483648 <= v <= 2147483647))
        if not fits and p.promotable: promoted.add((p.record_start, p.record_end))
    replacements = []
    for start, end in sorted(promoted):
        members = sorted((p for p in fields.values() if (p.record_start, p.record_end) == (start, end)), key=lambda p: p.offset)
        if not members or any(p.fmt == 'B' and p.promotable and p.value > 127 and p.id not in changes for p in members):
            raise ValueError('Set the complete coefficient tuple before widening an ambiguous legacy byte encoding.')
        values = [changes.get(p.id, p.value) for p in members]
        if len(members) == 1 and members[0].promotable:
            replacement = b'\x22' + raw[start + 1:start + 5] + struct.pack('<f', values[0])
        elif len(members) == 2 and all(p.promotable for p in members):
            replacement = raw[start:start + 5] + b'\xa2' + struct.pack('<ff', *values)
        elif len(members) == 3 and all(p.promotable for p in members):
            replacement = raw[start:start + 5] + b'\xa3\x02' + struct.pack('<fff', *values)
        elif len(members) == 3 and all(p.promotable for p in members[:2]) and members[2].fmt == 'B':
            replacement = raw[start:start + 5] + b'\xa3\x00' + struct.pack('<ffB', *values[:2], int(values[2]))
        else:
            raise ValueError('This numeric property cannot be widened using a documented encoding.')
        replacements.append((start, end, replacement))
    for key, v in changes.items():
        p = fields[key]
        if (p.record_start, p.record_end) not in promoted:
            struct.pack_into('<' + p.fmt, out, p.offset, v if p.fmt == 'f' else int(v))
    delta = 0
    for start, end, replacement in reversed(replacements):
        out[start:end] = replacement
        delta += len(replacement) - (end - start)
    if delta:
        old_start, old_end = shcb_region(raw)
        struct.pack_into('<I', out, 8, len(out))
        struct.pack_into('<I', out, 20, old_end - old_start + delta)
        if struct.unpack_from('<I', raw, 12)[0] == 2:
            struct.pack_into('<I', out, 36, old_end + delta)
    # Parse again, including the documented section registers after widening.
    parsed = {p.id: p.value for p in decode(kind, bytes(out))}
    for key, value in changes.items():
        if key not in parsed or not math.isclose(parsed[key], value, rel_tol=1e-6, abs_tol=1e-9):
            raise ValueError('The edited parameter did not round-trip: ' + key)
    return bytes(out)


def vdfm_references(raw: bytes) -> dict:
    """Post-1.4 VDFM layout: lengths/padding and data map determine all positions."""
    if len(raw) < 48 or raw[:4] != b'Q\x02\x01\x04':
        raise ValueError('Unsupported VDFM header.')
    data_length = struct.unpack_from('<I', raw, 16)[0]
    string_length = struct.unpack_from('<I', raw, 24)[0]
    map_length = struct.unpack_from('<I', raw, 32)[0]
    strings = 48 + data_length + raw[21]
    map_start = strings + string_length + raw[29]
    if data_length < 96 or not 0 < string_length <= 65536 or map_length % 8 or map_start + map_length > len(raw):
        raise ValueError('Invalid VDFM string or data-map boundaries.')
    mapped = {struct.unpack_from('<Q', raw, p)[0] for p in range(map_start, map_start + map_length, 8)}
    result = {}
    for offset, key in ((8, 'cdf'), (24, 'edf'), (32, 'cmf'), (40, 'tbf'),
                        (56, 'fmf'), (64, 'gdf'), (72, 'sdf'), (80, 'collision'), (88, 'tyres')):
        if offset not in mapped:
            continue
        pointer = struct.unpack_from('<I', raw, 48 + offset)[0]
        if not 0 <= pointer < string_length:
            raise ValueError('A VDFM physics reference is outside its string pool.')
        tail = raw[strings + pointer:map_start]
        stop = tail.find(b'\0')
        if stop < 0:
            raise ValueError('Unterminated VDFM physics reference.')
        value = tail[:stop].decode('ascii')
        if not re.fullmatch(r'[A-Za-z0-9_ .-]{1,256}', value):
            raise ValueError('Invalid VDFM physics reference.')
        result[key] = value
    return result


def private_donor_vdf(raw: bytes, references: dict[str, str]) -> bytes:
    """Clone donor geometry; append private core links without losing pool data."""
    original = vdfm_references(raw)
    if set(references) != {'cdf', 'edf', 'gdf'} or not references.keys() <= original.keys():
        raise ValueError('Complete, mapped chassis, engine and gearbox links are required.')
    length = struct.unpack_from('<I', raw, 24)[0]
    strings = 48 + struct.unpack_from('<I', raw, 16)[0] + raw[21]
    map_start = strings + length + raw[29]
    pool = bytearray(raw[strings:map_start])
    out, pointers = bytearray(raw[:strings]), {}
    for role in ('cdf', 'edf', 'gdf'):
        value = references[role]
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_ .-]{1,160}', value):
            raise ValueError('Invalid private donor component name.')
        if value == original[role]: continue
        if value not in pointers:
            pointers[value] = len(pool)
            pool += value.encode('ascii') + b'\0'
        struct.pack_into('<I', out, 48 + {'cdf': 8, 'edf': 24, 'gdf': 64}[role], pointers[value])
    if not pointers: return raw
    if len(pool) > 65536: raise ValueError('The cloned VDF string pool is too large.')
    padding = (-len(pool) - strings) % 16
    struct.pack_into('<I', out, 24, len(pool)); out[29] = padding
    out += pool + b'\0' * padding + raw[map_start:]
    if vdfm_references(bytes(out)) != original | references:
        raise ValueError('The private donor links failed verification.')
    return bytes(out)


def edit_tyres(raw: bytes, tyre_model: str) -> bytes:
    refs = vdfm_references(raw)
    if 'tyres' not in refs:
        raise ValueError('The tyre-model reference is unavailable.')
    if refs['tyres'] == tyre_model:
        return raw
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}', tyre_model):
        raise ValueError('Choose an installed tyre-model reference.')
    strings = 48 + struct.unpack_from('<I', raw, 16)[0] + raw[21]
    length = struct.unpack_from('<I', raw, 24)[0]
    map_start = strings + length + raw[29]
    pointer = struct.unpack_from('<I', raw, 48 + 88)[0]
    # Editing only an unshared, final string slot avoids relocating binary sections.
    others = [struct.unpack_from('<I', raw, 48 + off)[0] for off in (8, 24, 32, 40, 56, 64, 72, 80)
              if 48 + off + 4 <= strings]
    if pointer in others or any(pointer < p < length for p in others):
        raise ValueError('This VDFM shares the tyre string or has strings after it; tyre editing is read-only.')
    payload = tyre_model.encode('ascii') + b'\0'
    capacity = map_start - strings - pointer
    if len(payload) > capacity:
        raise ValueError('The new tyre reference does not fit this VDFM string slot.')
    new_length = pointer + len(payload)
    padding = map_start - strings - new_length
    if not 0 <= padding <= 255:
        raise ValueError('The new tyre string padding cannot be represented.')
    out = bytearray(raw)
    out[strings + pointer:map_start] = payload.ljust(capacity, b'\0')
    struct.pack_into('<I', out, 24, new_length)
    out[29] = padding
    if vdfm_references(bytes(out)).get('tyres') != tyre_model:
        raise ValueError('Could not verify the changed tyre reference.')
    return bytes(out)


def metrics(parameters: list[Parameter]) -> tuple[dict, list[dict]]:
    lookup = {p.id: p.value for p in parameters}
    def value(kind, key, component=0): return lookup.get(f'{kind}.{key}.0.{component}')
    def default(kind, key, setting):
        base = value(kind, key)
        if base is None: return None
        step = value(kind, key, 1) or 0
        return base + step * (value(kind, setting) or 0)
    mass, multiplier = value('cdf', 'mass'), value('cdf', 'power_multiplier')
    limiter = default('edf', 'rev_limit', 'rev_setting')
    curves = []
    tables = sorted({int(p.id.split('.')[2]) for p in parameters if p.id.startswith('edf.rpm.')})
    for table in tables:
        rows = []
        for p in parameters:
            if p.id.startswith(f'edf.rpm.{table}.'):
                row = p.id.split('.')[-1]
                torque = lookup.get(f'edf.torque.{table}.{row}')
                if torque is not None:
                    rows.append({'rpm': p.value, 'torque': torque, 'compression': lookup.get(f'edf.compression.{table}.{row}'),
                                 'torque_id': f'edf.torque.{table}.{row}'})
        curves.append({'map': table + 1, 'rows': rows})
    points = (curves[0]['rows'] if curves else [])
    # Interpolate the limiter boundary, rather than using inaccessible over-rev power.
    usable = [p for p in points if limiter is None or p['rpm'] <= limiter]
    if limiter is not None:
        for a, b in zip(points, points[1:]):
            if a['rpm'] < limiter < b['rpm']:
                usable.append({'rpm': limiter, 'torque': a['torque'] + (b['torque'] - a['torque']) *
                               (limiter - a['rpm']) / (b['rpm'] - a['rpm'])})
    raw_peak = max((p['torque'] * p['rpm'] * math.pi / 30000 for p in usable), default=None)
    kw = raw_peak * multiplier if raw_peak is not None and multiplier is not None else None
    torque = max((p['torque'] for p in usable), default=None)
    result = {'mass': mass, 'curve_kw': raw_peak, 'power_kw': kw,
              'power_hp': kw / 0.745699872 if kw is not None else None,
              'power_to_weight': kw / (mass / 1000) if kw is not None and mass else None,
              'peak_torque': torque * multiplier if torque is not None and multiplier is not None else None,
              'rev_limit': limiter, 'power_multiplier': multiplier, 'body_drag': value('cdf', 'body_drag'),
              'cg_height': value('cdf', 'cg_height'), 'rear_weight_share': default('cdf', 'cg_rear', 'cg_rear_setting'),
              'displacement': value('edf', 'displacement'), 'engine_inertia': value('edf', 'engine_inertia'),
              'fuel_capacity': None, 'forward_gears': value('cdf', 'forward_gears'),
              'first_gear_ratio': None, 'top_gear_ratio': None, 'final_drive_ratio': None,
              'front_brake_torque': None, 'rear_brake_torque': None,
              'yaw_inertia': value('cdf', 'inertia', 1)}
    for axle, occurrence in [('front', 0), ('rear', 2)]:
        def corner_default(key, setting):
            values = [lookup.get(f'cdf.{key}.{occurrence}.{i}') for i in range(2)]
            setting_value = lookup.get(f'cdf.{setting}.{occurrence}.0')
            return values[0] + values[1] * setting_value if all(v is not None for v in values) and setting_value is not None else None
        spring = corner_default('spring_range', 'spring_setting')
        multiplier = lookup.get(f'cdf.spring_multiplier.{occurrence}.0')
        result[axle + '_spring_proxy'] = spring * multiplier if spring is not None and multiplier is not None else None
        result[axle + '_ride_height'] = corner_default('ride_height', 'ride_height_setting')
        for key in ('bump_travel', 'rebound_travel', 'bumpstop_spring', 'bumpstop_rising'):
            result[axle + '_' + key] = lookup.get(f'cdf.{key}.{occurrence}.0')
        result[axle + '_arb_proxy'] = (default('cdf', axle + '_arb_range', axle + '_arb_setting')
                                     if value('cdf', 'spring_based_arb') == 1 else None)
    fuel = [value('cdf', 'fuel_range', i) for i in range(3)]
    if all(v is not None for v in fuel): result['fuel_capacity'] = fuel[0] + fuel[1] * max(0, fuel[2] - 1)
    for axle, corners in [('front', ('Front left', 'Front right')), ('rear', ('Rear left', 'Rear right'))]:
        values = [p.value for p in parameters if p.id.startswith('cdf.brake_torque.') and any(c in p.label for c in corners)]
        if values: result[axle + '_brake_torque'] = sum(values) / len(values)
    for wing in ('fw', 'rw'):
        coefficients = [value('cdf', wing + '_lift', i) for i in range(3)]
        angle = default('cdf', wing + '_range', wing + '_setting')
        result[wing + '_lift'] = sum(v * angle ** i for i, v in enumerate(coefficients)) if angle is not None and all(v is not None for v in coefficients) else None
    result['wing_lift'] = -(result['fw_lift'] + result['rw_lift']) if all(result[x] is not None for x in ('fw_lift', 'rw_lift')) else None
    def ratio(section, option):
        if option is None or option != int(option): return None
        driver = lookup.get(f'gdf.{section}.{int(option)}.0')
        driven = lookup.get(f'gdf.{section}.{int(option)}.1')
        return driven / driver if driver and driven else None
    result['first_gear_ratio'] = ratio('gear', value('cdf', 'gear1_setting'))
    gear_count = result['forward_gears']
    if gear_count is not None and gear_count == int(gear_count):
        result['top_gear_ratio'] = ratio('gear', value('cdf', 'gear' + str(int(gear_count)) + '_setting'))
    final = ratio('final', value('cdf', 'final_setting'))
    bevel = ratio('bevel', 0)
    if final is not None and bevel is not None: result['final_drive_ratio'] = final * bevel
    return result, curves


METRICS = [
    ('mass', 'Mass', 'kg', 'Chassis file mass; excludes setup fuel.'),
    ('power_hp', 'Engine power proxy', 'hp', 'Map 1 torque × RPM × chassis power multiplier, capped at the default rev limiter. Boost, air restrictors and engine-specific modifiers are not simulated.'),
    ('power_to_weight', 'Power / mass proxy', 'kW/t', 'Calculated engine power proxy divided by chassis mass.'),
    ('peak_torque', 'Torque proxy', 'Nm', 'Map 1 torque × chassis power multiplier, within the default rev limiter.'),
    ('rev_limit', 'Default rev limiter', 'rpm', 'Encoded default engine rev limit.'),
    ('displacement', 'Displacement', 'L', 'Encoded engine displacement.'),
    ('engine_inertia', 'Engine inertia', 'kg·m²', 'Engine inertia affects response; it is not an acceleration time.'),
    ('body_drag', 'Body base drag', 'coefficient', 'Base coefficient only; total drag depends on wings, ride height and cooling settings.'),
    ('wing_lift', 'Wing lift proxy', 'coefficient', 'Negative front + rear lift polynomials at default wing settings. Excludes diffuser/body/ride-height effects; this is not total downforce.'),
    ('yaw_inertia', 'Turning inertia', 'kg·m²', 'Encoded body inertia about the vertical axis; affects direction changes, not steady-state tyre grip.'),
    ('front_spring_proxy', 'Front spring proxy', 'N/m', 'Front-left default spring range × spring multiplier. Suspension geometry is not simulated.'),
    ('rear_spring_proxy', 'Rear spring proxy', 'N/m', 'Rear-left default spring range × spring multiplier. Suspension geometry is not simulated.'),
    ('front_arb_proxy', 'Front anti-roll bar proxy', 'file units', 'Default spring-based bar rate. Excludes suspension geometry, tyre stiffness and garage setup changes; not total axle roll stiffness.'),
    ('rear_arb_proxy', 'Rear anti-roll bar proxy', 'file units', 'Default spring-based bar rate. Unavailable for diameter-based bars; not total axle roll stiffness.'),
    ('front_bump_travel', 'Front bump coordinate', 'm', 'Front-left encoded suspension coordinate with zero packers and zero ride height; not measured available wheel travel.'),
    ('rear_bump_travel', 'Rear bump coordinate', 'm', 'Rear-left encoded suspension coordinate with zero packers and zero ride height; not measured available wheel travel.'),
    ('front_rebound_travel', 'Front rebound coordinate', 'm', 'Front-left encoded extension limit; geometry and ride height determine usable droop.'),
    ('rear_rebound_travel', 'Rear rebound coordinate', 'm', 'Rear-left encoded extension limit; geometry and ride height determine usable droop.'),
    ('front_bumpstop_spring', 'Front bump-stop spring', 'N/m', 'Front-left initial stop spring rate; engagement depends on geometry, ride height and packers.'),
    ('rear_bumpstop_spring', 'Rear bump-stop spring', 'N/m', 'Rear-left initial stop spring rate; engagement depends on geometry, ride height and packers.'),
    ('front_bumpstop_rising', 'Front bump-stop progression', 'file units', 'Front-left rising stop coefficient. Unknown encodings remain unavailable.'),
    ('rear_bumpstop_rising', 'Rear bump-stop progression', 'file units', 'Rear-left rising stop coefficient. Unknown encodings remain unavailable.'),
    ('front_ride_height', 'Front default ride height', 'm', 'Encoded front-left default ride height; not dynamic on-track height.'),
    ('rear_ride_height', 'Rear default ride height', 'm', 'Encoded rear-left default ride height; not dynamic on-track height.'),
    ('cg_height', 'CG height', 'm', 'Encoded centre-of-gravity height.'),
    ('rear_weight_share', 'Rear weight share', 'share', 'Default rear weight share from chassis range and setting.'),
    ('fuel_capacity', 'Fuel capacity', 'L', 'Maximum of the encoded fuel range.'),
    ('forward_gears', 'Forward gears', '', 'Chassis gear count, not the number of gearbox options.'),
    ('first_gear_ratio', 'Default first gear', 'ratio', 'Driven / driver teeth in the gearbox option selected by the chassis default.'),
    ('top_gear_ratio', 'Default top gear', 'ratio', 'Default ratio of the highest forward gear. Setup changes may select another option.'),
    ('final_drive_ratio', 'Default final drive', 'ratio', 'Default final-drive ratio multiplied by the gearbox bevel ratio.'),
    ('front_brake_torque', 'Front brake torque', 'Nm', 'Mean encoded brake torque of decoded front corners.'),
    ('rear_brake_torque', 'Rear brake torque', 'Nm', 'Mean encoded brake torque of decoded rear corners.'),
]
