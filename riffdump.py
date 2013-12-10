#!/usr/bin/python


from Avi import MainHeader, StreamHeader, OldIndexEntry


from pprint import pprint
import os
import struct
import sys


list_types = frozenset(("RIFF", "LIST"))


def read_4cc(stream):
	return stream.read(4)


def read_uint32(stream):
	return struct.unpack("<I", stream.read(4))[0]


def read_chunk(stream):
	fcc = read_4cc(stream)
	if fcc:
		return fcc, read_uint32(stream)
	return (None, None)


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
				header = MainHeader.from_stream(stream)
				pprint(header.__dict__)
			elif fourcc == "strh":
				header = StreamHeader.from_stream(stream)
				pprint(header.__dict__)
			elif fourcc == "idx1":
				while size > 0:
					entry = OldIndexEntry.from_stream(stream)
					pprint(entry.__dict__)
					size -= OldIndexEntry.size()
			else:
				stream.seek(size, os.SEEK_CUR)


def main():
	with open(sys.argv[1], "rb") as stream:
		dump(stream)


if __name__ == '__main__':
	main()
