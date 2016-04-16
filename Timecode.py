import re


_DENOMINATOR = 1001000
_COMMON_FPS_NUM = (
    24000000,  # 23.976
    24024000,  # 24
    25025000,  # 25
    30000000,  # 29.97
    30030000,  # 30
    50050000,  # 50
    60000000,  # 59.94
    60060000   # 60
)

_TOLERANCE = 900
_SNAP_FPS_MIN = (_COMMON_FPS_NUM[0] - _TOLERANCE) / _DENOMINATOR
_SNAP_FPS_MAX = (_COMMON_FPS_NUM[-1] + _TOLERANCE) / _DENOMINATOR

EXACT_29_97 = 30000000 / _DENOMINATOR


def interpret_frame_rate(ufps):
    """Adjusts a frame rate, expressed as frames per second, to a common
    standard if one closely matches."""
    ufps = float(ufps)
    if ufps < _SNAP_FPS_MIN or ufps > _SNAP_FPS_MAX:
        return ufps
    bfps = ufps * _DENOMINATOR
    min_diff = 1 << 31
    nearest = None
    for t in _COMMON_FPS_NUM:
        diff = abs(t - bfps)
        if diff < min_diff:
            min_diff = diff
            nearest = t
    if min_diff <= _TOLERANCE:
        return nearest / _DENOMINATOR
    return ufps

def _sum_frames(units, fps):
    frames = 0
    factor = 1
    for u, f in zip(units, (1, fps, 60, 60)):
        factor *= f
        frames += u * factor
    return frames


def parse_timecode(t, fps, is_drop_frame=None):
    """Parses a timecode, returning the result as a frame number.

    Keyword arguments:
    t -- The timecode to parse, a string containing numbers separated by ':',
        ';' or '.'.  Up to 4 numbers will be parsed, representing, from left to
        right, hours, minutes, seconds and frames.  The string can contain
        contiguous separators, in which case the number between them will be
        interpreted as zero.
    fps -- The number of frames per second.
    is_drop_frame -- Whether to consider this timecode to be drop-frame. This
        will only be considered if fps is close to 29.97, in which case possible
        values are:
            True -- Timecode is drop-frame
            False -- Timecode is not drop-frame
            None (default) -- Auto-detect based on the separators in the
                timecode string. The timecode will be considered drop-frame if
                the separator between seconds and frames is ';' or '.'.
    """
    fps = interpret_frame_rate(fps)

    negative = False

    if t[0] == "-":
        negative = True
        t = t[1:]

    parts = re.split(r"([:;.])", t)

    if fps == EXACT_29_97:
        if is_drop_frame is None:
            is_drop_frame = len(parts) > 1 and parts[-2] in ";."
    else:
        is_drop_frame = False

    if is_drop_frame:
        ref_fps = 30.0
    else:
        ref_fps = fps

    # reverse ordering of time units smallest to largest
    # and remove separators caught by the regex
    # int(n or 0) resolves to 0 in the case of empty strings
    units = [ int(n or 0) for n in parts[-1::-2] ]

    frame_n = _sum_frames(units, ref_fps)

    if is_drop_frame:
        single_minutes = int(frame_n / 1800)
        ten_minutes = int(frame_n / 18000)
        frame_n += 2 * (ten_minutes - single_minutes)

    if negative:
        return -round(frame_n)

    return round(frame_n)
