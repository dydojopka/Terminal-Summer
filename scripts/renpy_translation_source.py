"""Read inert Ren'Py 7 RPYC syntax trees for the offline Steam importer."""

import io
import pickle
import pickletools
import struct
import zlib
from pathlib import Path


class _Node:
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        elif (isinstance(state, tuple) and len(state) == 2 and isinstance(state[1], dict)
              and (state[0] is None or isinstance(state[0], dict))):
            self.__dict__.update(state[0] or {})
            self.__dict__.update(state[1])
        elif (type(self).__name__ == "PyCode" and isinstance(state, tuple)
              and len(state) > 1 and isinstance(state[1], str)):
            self.source = state[1]
        else:
            raise pickle.UnpicklingError(f"Unexpected {type(self).__name__} state")


class _RevertableDict(dict):
    pass


class _Expression(str):
    # Python 2's PyExpr is a str with additional constructor metadata.
    def __new__(cls, text, *_metadata):
        return str.__new__(cls, text)


class _RpycReader(pickle.Unpickler):
    types = {}

    def find_class(self, module, name):
        if (module, name) == ("renpy.ast", "PyExpr"):
            return _Expression
        if (module, name) == ("renpy.python", "RevertableDict"):
            return _RevertableDict
        if module in {"renpy.ast", "renpy.atl"}:
            if name not in self.types:
                self.types[name] = type(name, (_Node,), {})
            return self.types[name]
        raise pickle.UnpicklingError(f"Unsupported RPYC global: {module}.{name}")

    def persistent_load(self, _pid):
        raise pickle.UnpicklingError("Persistent IDs are not allowed")


_OPCODES = frozenset("""
    APPEND APPENDS BINGET BININT BININT1 BININT2 BINPUT BINUNICODE BUILD
    EMPTY_DICT EMPTY_LIST EMPTY_TUPLE GLOBAL LONG_BINGET LONG_BINPUT MARK
    NEWFALSE NEWOBJ NEWTRUE NONE PROTO SETITEM SETITEMS SHORT_BINSTRING
    STOP TUPLE TUPLE1 TUPLE2 TUPLE3
""".split())


def read_rpyc(path: Path, *, slot: int):
    raw = path.read_bytes()
    header = b"RENPY RPC2"
    if not raw.startswith(header):
        raise ValueError(f"{path}: expected a Ren'Py 7 RPYC2 file")
    offset = len(header)
    while offset + 12 <= len(raw):
        number, start, size = struct.unpack_from("<III", raw, offset)
        offset += 12
        if not number:
            break
        if number == slot:
            if start < offset or not 0 < size <= len(raw) - start:
                break
            decoder = zlib.decompressobj()
            payload = decoder.decompress(raw[start:start + size], 32 * 1024 * 1024)
            if not decoder.eof or decoder.unused_data:
                raise ValueError(f"{path}: invalid or oversized RPYC payload")
            for op, _, _ in pickletools.genops(payload):
                if op.name not in _OPCODES:
                    raise ValueError(f"{path}: unexpected opcode {op.name}")
            _, statements = _RpycReader(io.BytesIO(payload), encoding="utf-8").load()
            return statements
    raise ValueError(f"{path}: missing or invalid RPYC slot {slot}")


def nodes(statements):
    """Walk source blocks, not runtime links such as Translate.next."""
    seen = set()
    stack = [statements]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(reversed(item))
        elif isinstance(item, _Node) and id(item) not in seen:
            seen.add(id(item))
            yield item
            for field in ("items", "entries", "block"):
                stack.append(getattr(item, field, None))


def kind(node):
    return type(node).__name__
