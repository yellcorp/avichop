import re


_DEN = 1001000.0
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
_SNAP_FPS_MIN = (_COMMON_FPS_NUM[0] - _TOLERANCE) / _DEN
_SNAP_FPS_MAX = (_COMMON_FPS_NUM[-1] + _TOLERANCE) / _DEN


def interpret_frame_rate(ufps):
	if ufps < _SNAP_FPS_MIN or ufps > _SNAP_FPS_MAX:
		return ufps
	bfps = ufps * _DEN
	min_diff = 1 << 31
	nearest = None
	for t in _COMMON_FPS_NUM:
		diff = abs(t - bfps)
		if diff < min_diff:
			min_diff = diff
			nearest = t
	if min_diff <= _TOLERANCE:
		return nearest / _DEN
	return ufps

def _sum_frames(units, fps):
	frames = 0
	factor = 1
	for u, f in zip(units, (1, fps, 60, 60, 24)):
		factor *= f
		frames += u * factor
	return frames


# when is_drop_frame is None, it will be auto-detected, which means drop frame
# timecodes will be assumed if the seconds/frames separator is a ; or a .
def parse_timecode(t, fps, is_drop_frame=None):
	fps = interpret_frame_rate(fps)

	negative = False

	if t[0] == "-":
		negative = True
		t.pop(0)

	parts = re.split(r"([:;.])", t)

	if fps == EXACT_29_97:
		if is_drop_frame is None:
			is_drop_frame = len(parts) > 1 and parts[-2] in ";."
	else:
		is_drop_frame = False

	if is_drop_frame:
		ref_fps = 30
	else:
		ref_fps = fps

	# reverse ordering of time units smallest to largest
	# and remove separators caught by the regex
	# int(n or 0) resolves to 0 in the case of empty strings
	units = [ int(n or 0) for n in parts[-1::-2] ]

	frame_n = _sum_frames(units, ref_fps)

	if is_drop_frame:
		single_minutes = int(frame_n / 1800.0)
		ten_minutes = int(frame_n / 18000.0)
		frame_n += 2 * (ten_minutes - single_minutes)

	if negative:
		return -round(frame_n)

	return round(frame_n)
