#!/usr/bin/python


from NamedStruct import NamedStruct
from pprint import pprint
import os
import struct
import sys


list_types = frozenset(("RIFF", "LIST"))


class AviMainHeader(NamedStruct):
	endian = "little"
	fields = [
		("I",   "MicroSecPerFrame"),
		("I",   "MaxBytesPerSec"),
		("I",   "PaddingGranularity"),
		("I",   "Flags"),
		("I",   "TotalFrames"),
		("I",   "InitialFrames"),
		("I",   "Streams"),
		("I",   "SuggestedBufferSize"),
		("I",   "Width"),
		("I",   "Height"),
		("16s", "Reserved")
	]

class AviStreamHeader(NamedStruct):
	endian = "little"
	fields = [
		("4s", "fccType"),
		("4s", "fccHandler"),
		("I",  "Flags"),
		("H",  "Priority"),
		("H",  "Language"),
		("I",  "InitialFrames"),
		("I",  "Scale"),
		("I",  "Rate"),
		("I",  "Start"),
		("I",  "Length"),
		("I",  "SuggestedBufferSize"),
		("I",  "Quality"),
		("I",  "SampleSize"),
		("H",  "left"),
		("H",  "top"),
		("H",  "right"),
		("H",  "bottom")
	]


def read_4cc(stream):
	return stream.read(4)


def read_uint32(stream):
	return struct.unpack("<I", stream.read(4))[0]


def read_chunk(stream):
	fcc = read_4cc(stream)
	if fcc:
		return fcc, read_uint32(stream)
	return (None, None)


def read_struct(stream, s):
	return s.unpack(stream.read(s.size))


def dump_fields(names, values):
	for n, v in zip(names, values):
		print " {0} = {1!r}".format(n, v)


DUMP_FORMAT = "{indent}{type}: {id!r} {size}"
def dump(stream):
	while True:
		fourcc, size = read_chunk(stream)
		if fourcc is None:
			return
		if fourcc in list_types:
			list_type = read_4cc(stream)
			print "{fourcc!r} {size} {list_type!r}".format(
				fourcc=fourcc, size=size, list_type=list_type)
		else:
			print "{fourcc!r} {size}".format(
				fourcc=fourcc, size=size)

			# chunks must be 2-byte aligned?
			if size & 1:
				size += 1

			if fourcc == "avih":
				header = AviMainHeader.from_stream(stream)
				pprint(header.__dict__)
			elif fourcc == "strh":
				header = AviStreamHeader.from_stream(stream)
				pprint(header.__dict__)
			else:
				stream.seek(size, os.SEEK_CUR)


def main():
	with open(sys.argv[1], "rb") as stream:
		dump(stream)


if __name__ == '__main__':
	main()
