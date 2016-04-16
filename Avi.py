import Timecode

from ctypes import LittleEndianStructure, c_char, c_int32, c_uint16, c_uint32
import collections
import math
import os
import pprint
import re
import struct
import sys


# http://www.alexander-noe.com/video/documentation/avi.pdf


_4CC_NULL = "\x00" * 4

_LIST_TYPES = frozenset(("RIFF", "LIST"))

_VFRAME_ID_PATTERN = re.compile(r"^(\d\d)(d[bc])$")
_VFRAME_ID_FORMAT = "{0:02d}{1:2s}"

_METERS_PER_INCH = 0.0254


F_HASINDEX =        0x00000010
F_MUSTUSEINDEX =    0x00000020
F_ISINTERLEAVED =   0x00000100
F_TRUSTCKTYPE =     0x00000800
F_WASCAPTUREFILE =  0x00010000
F_COPYRIGHTED =     0x00020000

class MainHeader(LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("MicroSecPerFrame",    c_uint32),
        ("MaxBytesPerSec",      c_uint32),
        ("PaddingGranularity",  c_uint32),
        ("Flags",               c_uint32),
        ("TotalFrames",         c_uint32),
        ("InitialFrames",       c_uint32),
        ("Streams",             c_uint32),
        ("SuggestedBufferSize", c_uint32),
        ("Width",               c_uint32),
        ("Height",              c_uint32),
        ("Reserved",            c_char * 16)
    ]


class StreamHeader(LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("fccType",             c_char * 4),
        ("fccHandler",          c_char * 4),
        ("Flags",               c_uint32),
        ("Priority",            c_uint16),
        ("Language",            c_uint16),
        ("InitialFrames",       c_uint32),
        ("Scale",               c_uint32),
        ("Rate",                c_uint32),
        ("Start",               c_uint32),
        ("Length",              c_uint32),
        ("SuggestedBufferSize", c_uint32),
        ("Quality",             c_uint32),
        ("SampleSize",          c_uint32),
        ("left",                c_uint16),
        ("top",                 c_uint16),
        ("right",               c_uint16),
        ("bottom",              c_uint16)
    ]


IF_LIST =     0x00000001
IF_KEYFRAME = 0x00000010
IF_NO_TIME =  0x00000100

class OldIndexEntry(LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("ChunkId", c_char * 4),
        ("Flags",   c_uint32),
        ("Offset",  c_uint32),
        ("Size",    c_uint32)
    ]


class BitmapInfoHeader(LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("Size",          c_uint32),
        ("Width",         c_int32),
        ("Height",        c_int32),
        ("Planes",        c_uint16),
        ("BitCount",      c_uint16),
        ("Compression",   c_char * 4),
        ("SizeImage",     c_uint32),
        ("XPelsPerMeter", c_int32),
        ("YPelsPerMeter", c_int32),
        ("ClrUsed",       c_uint32),
        ("ClrImportant",  c_uint32)
    ]


_Chunk = collections.namedtuple("_Chunk",
    ("fcc", "sub_fcc", "header_size", "content_length", "file_length"))


_IndexPointer = collections.namedtuple("_IndexPointer",
    ("chunk_id", "flags", "offset", "size"))


StreamInfo = collections.namedtuple("StreamInfo",
    ("header", "bitmap_info", "codec_data", "name"))


AviFrame = collections.namedtuple("AviFrame",
    ("frame_num", "frame_type", "flags", "data"))


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
    match = _VFRAME_ID_PATTERN.match(fcc)
    if match is None:
        return (None, None)
    return (int(match.group(1)), match.group(2))


class _RateMonitor(object):
    def __init__(self, fps, min_sample_count=0):
        self._fps = float(fps)
        self._num_samples = int(math.ceil(self._fps))
        self._samples = list()
        self._max = 0.0
        self._min_sample_count = min_sample_count

    def sample(self, size):
        if len(self._samples) == self._num_samples:
            self._samples.pop(0)
        self._samples.append(size)
        if len(self._samples) > self._min_sample_count:
            self._max = max(self._max, self.rate())

    def rate(self):
        if len(self._samples) > 0:
            return sum(self._samples) * self._fps / len(self._samples)
        return 0.0

    def max(self):
        if len(self._samples) > self._min_sample_count:
            return self._max
        return self.rate()


class VideoStream(object):
    def __init__(self, owner):
        self._owner = owner

        self.stream_num = -1
        self.width = 0
        self.height = 0
        self.frame_rate = 0.0
        self.frame_count = 0

        self.codec = _4CC_NULL
        self.codec_data = None
        self.suggested_buffer_size = 0
        self.bit_depth = 0
        self.compression = _4CC_NULL
        self.size_image = 0

    def set_from(self, other_stream):
        for field in ("width", "height", "frame_rate", "codec", "codec_data",
                "suggested_buffer_size", "bit_depth", "compression",
                "size_image"):
            setattr(self, field, getattr(other_stream, field))

    def duration(self):
        return self.frame_count / self.frame_rate

    def seconds_to_frame(self, seconds):
        return round(self.frame_rate * seconds)

    def timecode_to_frame(self, timecode):
        return Timecode.parse_timecode(timecode, self.frame_rate)


class OutputVideoStream(VideoStream):
    def write_frame(self, avi_frame):
        self._owner.write_stream_frame(self.stream_num, avi_frame)


class InputVideoStream(VideoStream):
    def get_frame(self, frame_num=None, seconds=None, timecode=None):
        if timecode is not None:
            frame_num = self.timecode_to_frame(timecode)
        elif seconds is not None:
            frame_num = self.seconds_to_frame(seconds)

        return self._owner.get_stream_frame(self.stream_num, frame_num)


class _AbsoluteField(object):
    def __init__(self, bytestream, pos=None):
        self._file = bytestream
        if pos is None:
            pos = bytestream.tell()
        self._pos = pos

    def update(self, data):
        self._file.seek(self._pos, os.SEEK_SET)
        self._file.write(data)
        self._file.seek(0, os.SEEK_END)


class _ChunkWriter(object):
    def __init__(self, bytestream, chunk_fcc, list_fcc=None):
        self._file = bytestream
        self._chunk_fcc = chunk_fcc
        self._list_fcc = list_fcc
        self._start_pos = bytestream.tell()
        self._write_header(0)

    def _write_header(self, byte_count):
        self._file.seek(self._start_pos)
        self._file.write(struct.pack(
            "<4sI", self._chunk_fcc, byte_count))
        if self._list_fcc is not None:
            self._file.write(self._list_fcc)
        self._file.seek(0, os.SEEK_END)

    def close(self):
        bytes_written = self._file.tell() - self._start_pos - 8
        if bytes_written & 1:
            # needs to be aligned to 2-bytes, but don't reflect this in the
            # length field
            self._file.write("\x00")
        self._write_header(bytes_written)
        self._file = None


class _OutputStreamState(object):
    def __init__(self):
        self.header_field = None
        self.bitmap_info_field = None


class AviOutput(object):
    def __init__(self, bytestream, debug=None):
        self._file = bytestream
        self._riff = self._new_chunk("RIFF", "AVI ")

        self._avih_field = None

        self._movi = None
        self._movi_offset = None

        self.frame_rate = 0.0
        self._rate_monitor = None

        self.width = 0
        self.height = 0

        self.video_streams = [ ]
        self._stream_states = None
        self._frame_index = bytearray()

        self._log = _Logger(debug)

    def microseconds_per_frame(self):
        return round(1e6 / Timecode.interpret_frame_rate(self.frame_rate))

    def new_stream(self, basis_stream=None):
        vs = OutputVideoStream(self)

        if basis_stream is not None:
            vs.set_from(basis_stream)

        vs.stream_num = len(self.video_streams)
        vs.width = self.width
        vs.height = self.height
        vs.frame_rate = self.frame_rate
        self.video_streams.append(vs)
        return vs

    def write_frame(self, avi_frame):
        self.video_streams[0].write_frame(avi_frame)

    def write_stream_frame(self, stream_num, avi_frame):
        if avi_frame is None:
            return

        if self._avih_field is None:
            self._write_hdrl()
        if self._movi is None:
            self._begin_movi()
        if self._rate_monitor is None:
            self._rate_monitor = _RateMonitor(self.frame_rate, self.frame_rate * 0.5)

        chunk_name = _VFRAME_ID_FORMAT.format(stream_num, avi_frame.frame_type)
        offset = self._file.tell()

        chunk = self._new_chunk(chunk_name)
        self._file.write(avi_frame.data)
        chunk.close()

        self._rate_monitor.sample(len(avi_frame.data) + 8)

        e = OldIndexEntry()
        e.ChunkId = chunk_name
        e.Flags = avi_frame.flags
        e.Offset = offset - self._movi_offset
        e.Size = len(avi_frame.data)

        self._frame_index.extend(e.pack())

        self.video_streams[stream_num].frame_count += 1

    def close(self):
        if self._movi:
            self._movi.close()
            self._movi = None
        self._write_index()
        self._update_main_header()
        self._update_stream_headers()
        self._riff.close()
        self._riff = None

    def _update_main_header(self):
        h = MainHeader()
        h.MicroSecPerFrame = self.microseconds_per_frame()
        h.MaxBytesPerSec = int(math.ceil(self._rate_monitor.max()))
        h.PaddingGranularity = 0
        h.Flags = F_HASINDEX | F_ISINTERLEAVED
        h.TotalFrames = sum(vs.frame_count for vs in self.video_streams)
        h.InitialFrames = 0
        h.Streams = len(self.video_streams)
        h.SuggestedBufferSize = max(vs.suggested_buffer_size for vs in self.video_streams)
        h.Width = self.width
        h.Height = self.height

        self._log.write("MaxBytesPerSec measured as {0}".format(h.MaxBytesPerSec))

        self._avih_field.update(h.pack())

    def _write_hdrl(self):
        hdrl = self._new_chunk("LIST", "hdrl")
        self._avih_field = self._alloc_struct_chunk("avih", MainHeader)
        self._stream_states = [ self._alloc_strl(s) for s in self.video_streams ]
        hdrl.close()

    def _alloc_strl(self, vs):
        state = _OutputStreamState()

        strl = self._new_chunk("LIST", "strl")
        state.header_field = self._alloc_struct_chunk("strh", StreamHeader)
        state.bitmap_info_field = self._alloc_struct_chunk("strf", BitmapInfoHeader)
        if vs.codec_data is not None:
            strd = self._new_chunk("strd")
            self._file.write(vs.codec_data)
            strd.close()
        strl.close()

        return state

    def _update_stream_headers(self):
        for vs, state in zip(self.video_streams, self._stream_states):
            self._update_stream_header(vs, state)

    def _update_stream_header(self, vs, state):
        sh = StreamHeader()
        sh.fccType = "vids"
        sh.fccHandler = vs.codec
        sh.Flags = 0
        sh.Priority = 0
        sh.Language = 0
        sh.InitialFrames = 0
        sh.Scale = 1e3
        sh.Rate = int(vs.frame_rate * 1e3)
        sh.Start = 0
        sh.Length = vs.frame_count
        sh.SuggestedBufferSize = vs.suggested_buffer_size
        sh.Quality = 10000
        sh.SampleSize = 0
        sh.left = 0
        sh.top = 0
        sh.right = vs.width
        sh.bottom = vs.height

        state.header_field.update(sh.pack())

        bih = BitmapInfoHeader()
        bih.Size = BitmapInfoHeader.size()
        bih.Width = vs.width
        bih.Height = vs.height
        bih.Planes = 1
        bih.BitCount = vs.bit_depth
        bih.Compression = vs.compression
        bih.SizeImage = vs.size_image
        bih.XPelsPerMeter = round(72 / _METERS_PER_INCH)
        bih.YPelsPerMeter = bih.XPelsPerMeter
        bih.ClrUsed = 0
        bih.ClrImportant = 0

        state.bitmap_info_field.update(bih.pack())

    def _begin_movi(self):
        self._movi = self._new_chunk("LIST", "movi")
        self._movi_offset = self._file.tell() - 4

    def _write_index(self):
        idx1 = self._new_chunk("idx1")
        self._file.write(self._frame_index)
        idx1.close()

    def _alloc_struct_chunk(self, fcc, named_struct):
        chunk = self._new_chunk(fcc)
        field = _AbsoluteField(self._file)
        self._file.write(named_struct().pack())
        chunk.close()
        return field

    def _new_chunk(self, chunk_fcc, list_fcc=None):
        return _ChunkWriter(self._file, chunk_fcc, list_fcc)


def _default_log_func(m):
    print(m, file=sys.stderr)

class _Logger(object):
    def __init__(self, log_func=None):
        if log_func is True:
            log_func = _default_log_func

        self._log_func = log_func

        if log_func:
            self.write = self._write
            self.writeobj = self._writeobj
        else:
            self.write = self._null_func
            self.writeobj = self._null_func

    def _write(self, message, *args, **kwargs):
        if args or kwargs:
            message = message.format(*args, **kwargs)
        self._log_func(message)

    def _writeobj(self, obj):
        try:
            d = obj.__dict__
            self._log_func(pprint.pformat(d))
        except AttributeError:
            self._log_func(repr(obj))

    def _null_func(self, *args, **kwargs):
        pass


class AviInput(object):
    def __init__(self, bytestream, debug=None):
        self._file = bytestream

        self.file_header = None
        self.max_bytes_per_sec = 0

        self.video_streams = None
        self._stream_data = None
        self._stream_indices = None

        self._movi_offset = None

        self._log = _Logger(debug)

        self._parse()

    def get_frame(self, frame_num=None, seconds=None, timecode=None):
        # convenience method which maps to the get_frame method of the
        # first video stream, which is by far the common case
        return self.video_streams[0].get_frame(frame_num, seconds, timecode)

    def get_stream_frame(self, stream_num, frame_num):
        index = self._stream_indices[stream_num]

        if frame_num < 0 or frame_num >= len(index):
            return None

        frame_info = index[frame_num]

        frame_type = frame_info.chunk_id[2:]

        # +8 to skip chunk header
        self._file.seek(self._movi_offset + frame_info.offset + 8)
        data = self._file.read(frame_info.size)

        return AviFrame(frame_num, frame_type, frame_info.flags, data)

    def _parse(self):
        self._require_chunk("RIFF", "AVI ")
        self._parse_hdrl()

        movi = self._find_chunk("LIST", "movi")
        self._movi_offset = self._file.tell() - 4
        self._log.write("movi_offset = {0:x}", self._movi_offset)
        self._skip_chunk(movi)

        if self._parse_idx1():
            self._check_index_offsets()
        else:
            self._build_index()

        for vs in self.video_streams:
            vs.frame_count = len(self._stream_indices[vs.stream_num])
            self._log.writeobj(vs)

    def _parse_hdrl(self):
        self._require_chunk("LIST", "hdrl")
        avih = self._require_chunk("avih")
        self.file_header = self._read_struct_chunk(avih, MainHeader)
        self.max_bytes_per_sec = self.file_header.MaxBytesPerSec

        self._log.write("File header")
        self._log.writeobj(self.file_header)

        self.video_streams = [ ]
        self._stream_data = [ ]
        while self._parse_stream():
            pass

    def _parse_stream(self):
        while True:
            strl = self._next_chunk()
            # search for next LIST/strl chunk
            if strl.fcc == "LIST" and strl.sub_fcc == "strl":
                break
            # skip LIST/odml chunks
            elif strl.fcc == "LIST" and strl.sub_fcc == "odml":
                self._skip_chunk(strl)
            # back up if anything else is found
            else:
                self._put_back(strl)
                return False

        self._log.write("Stream definition #{0}".format(len(self._stream_data)))

        strh = self._require_chunk("strh")
        stream_header = self._read_struct_chunk(strh, StreamHeader)

        self._log.write("Stream header")
        self._log.writeobj(stream_header)

        bitmap_info = None
        strf = self._require_chunk("strf")
        if stream_header.fccType == "vids":
            bitmap_info = self._read_struct_chunk(strf, BitmapInfoHeader)
            self._log.write("Bitmap info header")
            self._log.writeobj(bitmap_info)
        else:
            self._skip_chunk(strf)

        codec_data = None
        c = self._next_chunk()
        if c.fcc == "strd":
            codec_data = self._read_chunk_content(c)
            self._log.write("Codec data: {0} bytes", len(codec_data))
            c = self._next_chunk()

        stream_name = None
        if c.fcc == "strn":
            stream_name = _from_asciiz(self._read_chunk_content(c))
            self._log.write("Stream name: {0!r}", stream_name)
        else:
            self._put_back(c)

        if bitmap_info is not None:
            vs = InputVideoStream(self)

            vs.stream_num = len(self._stream_data)
            vs.width = bitmap_info.Width
            vs.height = bitmap_info.Height
            vs.frame_rate = Timecode.interpret_frame_rate(
                stream_header.Rate / float(stream_header.Scale))

            vs.codec = stream_header.fccHandler
            vs.codec_data = codec_data
            vs.suggested_buffer_size = stream_header.SuggestedBufferSize
            vs.bit_depth = bitmap_info.BitCount
            vs.compression = bitmap_info.Compression
            vs.size_image = bitmap_info.SizeImage

            self.video_streams.append(vs)

        self._stream_data.append(StreamInfo(
            stream_header, bitmap_info, codec_data, stream_name))

        return True

    def _parse_idx1(self):
        idx1 = self._next_chunk()
        if idx1.fcc != "idx1":
            self._log.write("idx1 not present")
            self._put_back(idx1)
            return False

        self._log.write("idx1 present")

        si = collections.defaultdict(list)
        entry_count = int(idx1.content_length / float(OldIndexEntry.size()))
        for n in range(0, entry_count):
            entry = OldIndexEntry.from_stream(self._file)
            if entry.Flags & IF_LIST == 0:
                stream_num, frame_type = _unpack_frame_fcc(entry.ChunkId)
                if stream_num is not None:
                    si[stream_num].append(_IndexPointer(
                        entry.ChunkId,
                        entry.Flags,
                        entry.Offset,
                        entry.Size))

                    self._log.write("#{0}: {1}",
                        stream_num,
                        pprint.pformat(entry.__dict__))

        # skip any slack space at the end of the idx1 data
        self._file.seek(
            idx1.file_length - entry_count * OldIndexEntry.size(),
            os.SEEK_CUR)

        self._stream_indices = si
        return True

    def _check_index_offsets(self):
        for index, track in self._stream_indices.items():
            if len(track) > 0:
                f = track[0]
                self._file.seek(self._movi_offset + f.offset)
                if self._file.read(4) != f.chunk_id:
                    print("Fixing offsets for track #{0}".format(index))
                    for g in track:
                        g.offset -= self._movi_offset
                else:
                    print("Offsets for track #{0} are correct".format(index))

    def _build_index(self):
        si = collections.defaultdict(list)

        self._file.seek(self._movi_offset, os.SEEK_SET)

        check = self._file.read(4)
        assert check == "movi", "_movi_offset should point to 'movi' string"

        while True:
            c = self._next_chunk()
            if c is None:
                break
            elif c.fcc != "LIST":
                stream_num, frame_type = _unpack_frame_fcc(c.fcc)
                if stream_num is not None:
                    si[stream_num].append(_IndexPointer(
                        c.fcc,
                        0,
                        self._file.tell() - c.header_size,
                        c.content_length))
                self._skip_chunk(c)

        self._stream_indices = si

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

    def _find_chunk(self, fcc, sub_fcc=None):
        while True:
            c = self._next_chunk()
            if c is None:
                return None
            if fcc == c.fcc and (sub_fcc is None or sub_fcc == c.sub_fcc):
                return c
            self._skip_chunk(c)

    def _next_chunk(self):
        while True:
            h = self._file.read(8)
            content_read = 0
            if len(h) == 0:
                return None
            fcc, content_length = struct.unpack("<4sI", h)
            file_length = content_length + (content_length & 1)

            if fcc == "JUNK":
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
