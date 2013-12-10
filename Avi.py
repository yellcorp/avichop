from NamedStruct import NamedStruct

import collections
import os
import pprint
import re
import struct
import sys


# http://www.alexander-noe.com/video/documentation/avi.pdf


_RIFF = "RIFF"
_LIST = "LIST"
_JUNK = "JUNK"

_LIST_TYPES = frozenset((_RIFF, _LIST))

_VFRAME_ID = re.compile(r"^(\d\d)(d[bc])$")


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


class IndexPointer(object):
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


_Chunk = collections.namedtuple("_Chunk", 
	("fcc", "sub_fcc", "header_size", "content_length", "file_length"))


_StreamInfo = collections.namedtuple("_StreamInfo",
	("header", "bitmap_info", "codec_data", "name"))


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


def _unpack_frame_fcc(fcc):
	match = _VFRAME_ID.match(fcc)
	if match is None:
		return (None, None)
	return (int(match.group(1)), match.group(2))


def _log(message, *args, **kwargs):
	if args or kwargs:
		message = message.format(*args, **kwargs)
	print >> sys.stderr, message


def _log_obj(obj):
	if hasattr(obj, "__dict__"):
		pprint.pprint(obj.__dict__, stream=sys.stderr)
	else:
		print >> sys.stderr, repr(obj)


def _null_func(*args, **kwargs):
	pass


class AviFile(object):
	def __init__(self, bytestream, debug=False):
		self._file = bytestream
		self._index = None
		self.file_header = None
		self._stream_data = [ ]
		self._movi_offset = None
		self._video_indices = None

		if debug:
			self._log = _log
			self._log_obj = _log_obj
		else:
			self._log = _null_func
			self._log_obj = _null_func

	def parse(self):
		self._require_chunk(_RIFF, "AVI ")
		self._parse_hdrl()

		movi = self._require_chunk(_LIST, "movi")
		self._movi_offset = self._file.tell() - 4
		self._skip_chunk(movi)

		if self._parse_idx1():
			self._check_index_offsets()
		else:
			self._build_index()

	def _parse_hdrl(self):
		self._require_chunk(_LIST, "hdrl")
		avih = self._require_chunk("avih")
		self.file_header = self._read_struct_chunk(avih, MainHeader)

		self._log("File header")
		self._log_obj(self.file_header)

		while self._parse_stream():
			pass

	def _parse_stream(self):
		strl = self._next_chunk()
		if strl.fcc != _LIST or strl.sub_fcc != "strl":
			self._put_back(strl)
			return False

		self._log("Stream definition")

		strh = self._require_chunk("strh")
		stream_header = self._read_struct_chunk(strh, StreamHeader)

		self._log("Stream header")
		self._log_obj(stream_header)

		bitmap_info = None
		strf = self._require_chunk("strf")
		if stream_header.fccType == "vids":
			bitmap_info = self._read_struct_chunk(strf, BitmapInfoHeader)
			self._log("Bitmap info header")
			self._log_obj(bitmap_info)
		else:
			self._skip_chunk(strf)

		codec_data = None
		c = self._next_chunk()
		if c.fcc == "strd":
			codec_data = self._read_chunk_content(c)
			self._log("Codec data: {0} bytes", len(codec_data))
			c = self._next_chunk()

		stream_name = None
		if c.fcc == "strn":
			stream_name = _from_asciiz(self._read_chunk_content(c))
			self._log("Stream name: {0!r}", stream_name)
		else:
			self._put_back(c)

		self._stream_data.append(_StreamInfo(
			stream_header, bitmap_info, codec_data, stream_name))

		return True

	def _parse_idx1(self):
		idx1 = self._next_chunk()
		if idx1.fcc != "idx1":
			self._log("idx1 not present")
			self._put_back(idx1)
			return False

		self._log("idx1 present")

		vi = collections.defaultdict(list)
		entry_count = int(idx1.content_length / float(OldIndexEntry.size()))
		for n in xrange(0, entry_count):
			entry = OldIndexEntry.from_stream(self._file)
			if entry.Flags & IF_LIST == 0:
				stream_index, frame_type = _unpack_frame_fcc(entry.ChunkId)
				if stream_index is not None:
					vi[stream_index].append(IndexPointer(
						entry.ChunkId,
						entry.Flags,
						entry.Offset,
						entry.Size))

					self._log("#{0}: {1}",
						stream_index,
						pprint.pformat(entry.__dict__))

		# skip any slack space at the end of the idx1 data
		self._file.seek(
			idx1.file_length - entry_count * OldIndexEntry.size(),
			os.SEEK_CUR)

		self._video_indices = vi
		return True

	def _check_index_offsets(self):
		for index, track in self._video_indices.iteritems():
			if len(track) > 0:
				f = track[0]
				self._file.seek(self._movi_offset + f.offset)
				if self._file.read(4) != f.id:
					print "Fixing offsets for track #{0}".format(index)
					for g in track:
						g.offset -= self._movi_offset
				else:
					print "Offset for track #{0} are correct".format(index)

	def _build_index(self):
		vi = collections.defaultdict(list)

		self._file.seek(self._movi_offset, os.SEEK_SET)

		check = self._file.read(4)
		assert check == "movi", "_movi_offset should point to 'movi' string"

		while True:
			c = self._next_chunk()
			if c is None:
				break
			elif c.fcc != _LIST:
				stream_index, frame_type = _unpack_frame_fcc(c.fcc)
				if stream_index is not None:
					vi[stream_index].append(IndexPointer(
						c.fcc,
						0,
						self._file.tell() - c.header_size,
						c.content_length))
				self._skip_chunk(c)

	def _read_struct_chunk(self, chunk, named_struct):
		s = named_struct.from_stream(self._file)
		slack = chunk.file_length - named_struct.size()
		if slack > 0:
			self._file.seek(slack, os.SEEK_CUR)
		return s

	def _read_chunk_content(self, chunk):
		return self._file.read(chunk.file_length)[:chunk.content_length]

	def _require_chunk(self, fcc, sub_fcc=None):
		c = self._next_chunk()
		_expect_equal("chunk", fcc, c.fcc)
		if sub_fcc is not None:
			_expect_equal("list", sub_fcc, c.sub_fcc)
		return c

	def _next_chunk(self):
		while True:
			h = self._file.read(8)
			content_read = 0
			if len(h) == 0:
				return None
			fcc, content_length = struct.unpack("<4sI", h)
			file_length = content_length + (content_length & 1)

			if fcc == _JUNK:
				self._file.seek(file_length, os.SEEK_CUR)
			else:
				list_fcc = None
				if fcc in _LIST_TYPES:
					list_fcc = self._file.read(4)
					content_read += 4
				return _Chunk(fcc, list_fcc,
					# 'header_size' attribute includes the size of the chunk header
					# which is the assumption _put_back makes
					content_read + 8,
					content_length - content_read, 
					file_length - content_read)

	def _skip_chunk(self, chunk):
		self._file.seek(chunk.file_length, os.SEEK_CUR)

	def _put_back(self, chunk):
		self._file.seek(-chunk.header_size, os.SEEK_CUR)
