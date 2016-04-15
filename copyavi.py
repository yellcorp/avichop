#!/usr/bin/env python3


import sys

import Avi


def copy_avi(in_stream, out_stream):
	in_avi = Avi.AviInput(in_stream, debug=True)
	out_avi = Avi.AviOutput(out_stream)

	out_avi.max_bytes_per_sec = in_avi.max_bytes_per_sec

	in_v = in_avi.video_streams[0]
	out_avi.frame_rate = in_v.frame_rate
	out_avi.width = in_v.width
	out_avi.height = in_v.height

	out_v = out_avi.new_stream(in_v)

	for f in range(0, in_v.frame_count):
		out_v.write_frame(in_v.get_frame(f))

	out_avi.close()


def main():
	with open(sys.argv[1], "rb") as in_stream:
		with open(sys.argv[2], "wb") as out_stream:
			copy_avi(in_stream, out_stream)


if __name__ == '__main__':
	main()
