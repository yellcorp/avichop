from NamedStruct import NamedStruct


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
