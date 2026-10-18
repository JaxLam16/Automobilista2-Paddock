"""Explicit units and deterministic spoken numbers; unknown inputs are never zero."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


ONES = ('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen '
        'fifteen sixteen seventeen eighteen nineteen').split()
TENS = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()


def integer_words(number):
    if type(number) is not int or not 0 <= number <= 999999:
        raise ValueError('Spoken integer is outside the supported range.')
    if number < 20:
        return ONES[number]
    if number < 100:
        return TENS[number//10]+('-'+ONES[number%10] if number%10 else '')
    if number < 1000:
        return ONES[number//100]+' hundred'+(' '+integer_words(number%100) if number%100 else '')
    return integer_words(number//1000)+' thousand'+(' '+integer_words(number%1000) if number%1000 else '')


def numeric(value, *, minimum=None, maximum=None):
    if value is None or isinstance(value,bool):
        raise ValueError('A measured finite number is required.')
    try:
        result = Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):
        raise ValueError('A measured finite number is required.') from None
    if (not result.is_finite() or abs(result)>999999
            or (minimum is not None and result<minimum) or (maximum is not None and result>maximum)):
        raise ValueError('Number is missing or outside the supported range.')
    return result


def rounded(number, places):
    value = number.quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP)
    return abs(value) if value == 0 else value


def decimal_words(number):
    text = format(number,'f')
    whole, _, fraction = text.lstrip('-').partition('.')
    return ('minus ' if number<0 else '')+integer_words(int(whole))+(
        ' point '+' '.join(ONES[int(n)] for n in fraction) if fraction else '')


@dataclass(frozen=True)
class Formatted:
    text: str
    speech: str


def quantity(value, places, unit, spoken_unit=None):
    value = rounded(value,places)
    return Formatted(f'{value:.{places}f} {unit}',decimal_words(value)+' '+(spoken_unit or unit))


@dataclass(frozen=True)
class Units:
    distance: str = 'm'
    pressure: str = 'bar'
    temperature: str = 'c'
    fuel: str = 'litres'

    def __post_init__(self):
        choices = {'distance':('m','ft'),'pressure':('bar','psi'),
                   'temperature':('c','f'),'fuel':('litres','us_gallons','laps')}
        if any(getattr(self,key) not in values for key,values in choices.items()):
            raise ValueError('Choose valid coach units.')

    def update(self, values):
        if not isinstance(values,dict) or set(values)-set(asdict(self)):
            raise ValueError('Unknown coach units.')
        return replace(self,**values)


class Numbers:
    def __init__(self, units=None):
        self.units = units or Units()

    def gap(self, seconds):
        value = numeric(seconds,minimum=0,maximum=86400)
        return quantity(value,1 if rounded(value,1)<10 else 0,'s','seconds')

    def delta(self, seconds):
        value = rounded(numeric(seconds,minimum=-999,maximum=999),1)
        result = quantity(value,1,'s','seconds')
        return Formatted(('+' if value>0 else '')+result.text,
                         ('plus ' if value>0 else '')+result.speech)

    def tenths(self, seconds):
        """A measured time loss: 'two tenths' below one second, then seconds."""
        value = rounded(numeric(seconds,minimum=0,maximum=999),1)
        if value < 1:
            count = int(value*10)
            return Formatted(f'{value:.1f} s',integer_words(count)+(' tenth' if count==1 else ' tenths'))
        return quantity(value,1,'s','seconds')

    def lap_time(self, seconds):
        value = rounded(numeric(seconds,minimum=0,maximum=3599.9),1)
        tenths = int(value*10)
        minutes, rest = divmod(tenths,600)
        secs, tenth = divmod(rest,10)
        if not minutes:
            speech = integer_words(secs)+' '+ONES[tenth]
        else:
            sec_words = ('zero zero' if secs==0 else 'oh '+ONES[secs] if secs<10 else integer_words(secs))
            speech = integer_words(minutes)+' '+sec_words+' '+ONES[tenth]
        return Formatted(f'{minutes}:{secs:02d}.{tenth}',speech)

    def temperature_c(self, celsius):
        value = numeric(celsius,minimum=-100,maximum=2000)
        if self.units.temperature=='f':
            return quantity(value*Decimal('1.8')+32,0,'°F','degrees Fahrenheit')
        return quantity(value,0,'°C','degrees Celsius')

    def pressure_bar(self, bar):
        value = numeric(bar,minimum=0,maximum=100)
        if self.units.pressure=='psi':
            return quantity(value*Decimal('14.503773773'),1,'psi','P S I')
        return quantity(value,2,'bar')

    def distance_m(self, metres):
        value = numeric(metres,minimum=0,maximum=100000)
        if self.units.distance=='ft':
            return quantity(value/Decimal('.3048'),0,'ft','feet')
        return quantity(value,0,'m','metres')

    def fuel_litres(self, litres, *, litres_per_lap=None):
        value = numeric(litres,minimum=0,maximum=2000)
        if self.units.fuel=='laps':
            consumption = numeric(litres_per_lap,minimum=Decimal('.001'),maximum=200)
            return quantity(value/consumption,1,'laps')
        if self.units.fuel=='us_gallons':
            return quantity(value/Decimal('3.785411784'),1,'US gal','U S gallons')
        return quantity(value,1,'L','litres')

    def fuel_burn(self, litres_per_lap):
        value = numeric(litres_per_lap,minimum=Decimal('.001'),maximum=2000)
        # Laps is a range unit. It cannot describe the physical burn per lap.
        if self.units.fuel=='us_gallons':
            return quantity(value/Decimal('3.785411784'),2,'US gal/lap','U S gallons per lap')
        return quantity(value,2,'L/lap','litres per lap')

    def examples(self):
        # Format examples only, never telemetry or a prediction.
        return {key:asdict(value) for key,value in {
            'gap':self.gap(1.24),'lap':self.lap_time(92.54),'delta':self.delta(-.14),
            'distance':self.distance_m(100),'temperature':self.temperature_c(90),
            'pressure':self.pressure_bar(1.85),'fuel':self.fuel_litres(20,litres_per_lap=2.5),
        }.items()}
