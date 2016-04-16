import ctypes

def read_structure(stream, structure_cls):
    buf = stream.read(ctypes.sizeof(structure_cls))
    return structure_cls.from_buffer_copy(buf)
