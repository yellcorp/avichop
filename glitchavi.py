#!/usr/bin/python


import sys

import Avi


def bounce(low, high, times):
	for r in xrange(0, times):
		for n in xrange(low, high):
			yield n
		for n in xrange(high, low, -1):
			yield n


def benedict(src, dest):
	for f in xrange(0, 6):
		dest.write_frame(src.get_frame(f))
	for r in xrange(0, 12):
		for f in xrange(3, 6):
			dest.write_frame(src.get_frame(f))


def repeat_some(src, dest):
	def repeat_count_for_frame(f):
		if f >= 2:
			return f
		return 1

	for f in xrange(0, src.frame_count):
		for x in xrange(0, repeat_count_for_frame(f)):
			frame = src.get_frame(f)
			dest.write_frame(frame)


def glitch_avi(in_stream, out_stream):
	in_avi = Avi.AviInput(in_stream, debug=True)
	out_avi = Avi.AviOutput(out_stream, debug=True)

	out_avi.max_bytes_per_sec = in_avi.max_bytes_per_sec

	src = in_avi.video_streams[0]
	out_avi.frame_rate = src.frame_rate
	out_avi.width = src.width
	out_avi.height = src.height

	dest = out_avi.new_stream(src)

	# repeat_some(src, dest)
	benedict(src, dest)

	out_avi.close()


def main():
	with open(sys.argv[1], "rb") as in_stream:
		with open(sys.argv[2], "wb") as out_stream:
			glitch_avi(in_stream, out_stream)


if __name__ == '__main__':
	main()
