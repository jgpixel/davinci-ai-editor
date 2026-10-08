"""Exact frame arithmetic. Decision ends are exclusive; API ends are calibrated."""
from fractions import Fraction


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a time value.')
    try:
        return Fraction(str(value).removesuffix('s'))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f'Invalid numeric timing value: {value!r}') from exc


def fps(value):
    value = str(value).replace(' DF', '').strip()
    aliases = {'23.976': Fraction(24000, 1001), '29.97': Fraction(30000, 1001),
               '59.94': Fraction(60000, 1001), '119.88': Fraction(120000, 1001)}
    result = number(value)
    for label, standard in aliases.items():
        if result == number(label):
            return standard
    # OTIO serializes rational frame rates as doubles. Restore their exact grids.
    for standard in aliases.values():
        if abs(result - standard) < Fraction(1, 1000000):
            return standard
    return result


def integer(value):
    result = number(value)
    if result.denominator != 1:
        raise ValueError(f'Subframe timing is unsupported: {value}')
    return int(result)


def snap(seconds, rate):
    """Nearest timeline frame, ties upward. Do not use binary floating arithmetic."""
    value = number(seconds) * fps(rate)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def file_to_timeline(clip, file_seconds, timeline_rate):
    """Map one occurrence, not an entire source. Returns exact timeline seconds."""
    rate = fps(timeline_rate)
    if fps(clip['source_fps']) != rate:
        raise ValueError('Mixed frame rates require a verified rate-conform implementation.')
    return str(Fraction(clip['start_frame'], 1) / rate + number(file_seconds)
               - Fraction(clip['source_start_frame'], 1) / rate)
