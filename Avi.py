from NamedStruct import NamedStruct

from pprint import pprint
import collections
import os
import re
import struct


# http://www.alexander-noe.com/video/documentation/avi.pdf


_4CC_RIFF = "RIFF"
_4CC_LIST = "LIST"
_4CC_JUNK = "JUNK"

_4CC_VSTREAM_ID = re.compile(r"^(\d\d)(d[bc])$")


F_HASINDEX =        0x00000010
F_MUSTUSEINDEX =    0x00000020
F_ISINTERLEAVED =   0x00000100
F_TRUSTCKTYPE =     0x00000800
F_WASCAPTUREFILE =  0x00010000
F_COPYRIGHTED =     0x00020000

class MainHeader(NamedStruct):
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


class StreamHeader(NamedStruct):
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


_4CC_AUDIO = "auds"
_4CC_MIDI =  "mids"
_4CC_TEXT =  "txts"
_4CC_VIDEO = "vids"


IF_LIST =     0x00000001
IF_KEYFRAME = 0x00000010
IF_NO_TIME =  0x00000100

class OldIndexEntry(NamedStruct):
	endian = "little"
	fields = [
		("4s", "ChunkId"),
		("I",  "Flags"),
		("I",  "Offset"),
		("I",  "Size")
	]


class IndexEntry(object):
	def __init__(self, chunk_id, flags, offset, size):
		self.id = chunk_id
		self.flags = flags
		self.offset = offset
		self.size = size

	def is_compressed(self):
		return self.id[3] == 'c'


class BitmapInfoHeader(NamedStruct):
	endian = "little"
	fields = [
		("I", "Size"),
		("i", "Width"),
		("i", "Height"),
		("H", "Planes"),
		("H", "BitCount"),
		("I", "Compression"),
		("I", "SizeImage"),
		("i", "XPelsPerMeter"),
		("i", "YPelsPerMeter"),
		("I", "ClrUsed"),
		("I", "ClrImportant")
	]


class FormatError(Exception):
	pass


def _expect_equal(noun, expect, got):
	if expect != got:
		raise FormatError("Expected {0} of type {1!r}, got {2!r}".format(
			noun, expect, got))


def _from_asciiz(s):
	z = s.find("\x00")
	if z >= 0:
		s = s[:z]
	return s.decode("cp1252")


class AviFile(object):
	def __init__(self, bytestream):
		self._file = bytestream
		self._index = None
		self.file_header = None
		self._stream_data = [ ]
		self._movi_offset = None
		self._vf_index = None

	def parse(self):
		self._expect_riff("AVI ")
		self._parse_hdrl()

		movi_size = self._expect_list("movi")
		self._movi_offset = self._file.tell() - 4
		self._file.seek(movi_size, os.SEEK_CUR)

		if self._parse_idx1():
			self._check_index_offsets()
		else:
			self._build_index()

	def _check_index_offsets(self):
		for index, track in self._vf_index.iteritems():
			if len(track) > 0:
				f = track[0]
				self._file.seek(self._movi_offset + f.offset)
				if self._file.read(4) != f.id:
					print "Fixing offsets for track #{0}".format(index)
					for g in track:
						g.offset -= self._movi_offset
				else:
					print "Offset for track #{0} are correct".format(index)

	def _parse_hdrl(self):
		hdrl_size = self._expect_list("hdrl")

		self._expect_chunk("avih")
		self.file_header = MainHeader.from_stream(self._file)

		print "File header"
		pprint(self.file_header.__dict__)

		while self._parse_stream():
			pass

	def _parse_stream(self):
		ch_4cc, size, list_4cc = self._read_list()

		if ch_4cc != _4CC_LIST or list_4cc != "strl":
			self._file.seek(-12, os.SEEK_CUR)
			return False

		print "Stream definition"

		self._expect_chunk("strh")
		stream_header = StreamHeader.from_stream(self._file)

		print "Stream header"
		pprint(stream_header.__dict__)

		bitmap_info = None
		strf_size = self._expect_chunk("strf")
		if stream_header.fccType == _4CC_VIDEO:
			bitmap_info = BitmapInfoHeader.from_stream(self._file)

			print "Bitmap info"
			pprint(bitmap_info.__dict__)
		else:
			self._file.read(strf_size)

		codec_data = None
		ch_4cc, size = self._read_chunk()
		if ch_4cc == "strd":
			codec_data = self._file.read(size)
			print "Codec data: {0} bytes".format(len(codec_data))
			ch_4cc, size = self._read_chunk()

		stream_name = None
		if ch_4cc == "strn":
			stream_name = _from_asciiz(self._file.read(size))
			print "Stream name: {0!r}".format(stream_name)
		else:
			self._file.seek(-8, os.SEEK_CUR)

		self._stream_data.append(AviFile.StreamInfo(
			stream_header, bitmap_info, codec_data, stream_name))

		return True

	def _parse_idx1(self):
		ch_4cc, size = self._read_chunk()
		if ch_4cc != "idx1":
			print "idx1 not present"
			return False

		print "idx1 present"

		self._vf_index = collections.defaultdict(list)
		for n in xrange(0, size, OldIndexEntry.size()):
			entry = OldIndexEntry.from_stream(self._file)
			if entry.Flags & IF_LIST == 0:
				match = _4CC_VSTREAM_ID.match(entry.ChunkId)
				if match is not None:
					stream_index = int(match.group(1))
					self._vf_index[stream_index].append(IndexEntry(
						entry.ChunkId,
						entry.Flags,
						entry.Offset,
						entry.Size))

					print "#{0}: ".format(stream_index),
					pprint(entry.__dict__)

		return True

	def _build_index(self):
		self._vf_index = collections.defaultdict(list)

		self._file.seek(self._movi_offset, os.SEEK_SET)

		check = self._read(4)
		assert check == "movi", "_movi_offset should point to 'movi' string"

		offset = 4
		while True:
			ch_4cc, size = self._read_chunk()
			if ch_4cc == _4CC_LIST:
				self._file.read(4)
				offset += 12
			else:
				match = _4CC_VSTREAM_ID.match(ch_4cc)
				if match is not None:
					stream_index = int(match.group(1))
					self._vf_index[stream_index].append(IndexEntry(
						ch_4cc,
						IF_KEYFRAME,
						offset,
						size))
					self._file.seek(size, os.SEEK_CUR)
					offset += 8 + size


	def _expect_riff(self, expect_4cc):
		return self._expect_generic_list(_4CC_RIFF, expect_4cc)

	def _expect_list(self, expect_4cc):
		return self._expect_generic_list(_4CC_LIST, expect_4cc)

	def _expect_generic_list(self, expect_4cc_chunk, expect_4cc_list):
		got_4cc_chunk, size, got_4cc_list = self._read_list()
		_expect_equal("chunk", expect_4cc_chunk, got_4cc_chunk)
		_expect_equal("list", expect_4cc_list, got_4cc_list)
		return size - 4

	def _expect_chunk(self, expect_4cc):
		got_4cc, size = self._read_chunk()
		_expect_equal("chunk", expect_4cc, got_4cc)
		return size

	def _read_chunk(self):
		while True:
			b = self._file.read(8)
			if len(b) == 0:
				return (None, 0)
			fcc, size = struct.unpack("<4sI", b)
			if fcc == _4CC_JUNK:
				self._file.seek(size, os.SEEK_CUR)
			else:
				return fcc, size

	def _read_list(self):
		fcc, size = self._read_chunk()
		if fcc is None:
			return (None, 0, None)
		return fcc, size, self._file.read(4)

	class StreamInfo(object):
		def __init__(self, header, bitmap_info, codec_data, name):
			self.header = header
			self.bitmap_info = bitmap_info
			self.codec_data = codec_data
			self.name = name
