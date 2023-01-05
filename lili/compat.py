import marshal
import sys
from types import CodeType
from typing import BinaryIO, Union

Version = tuple[Union[int, str], ...]


# breaking version changes that need special handling, see below
# <https://github.com/python/cpython/blob/main/Lib/importlib/_bootstrap_external.py>

# 2-byte opcodes regardless of HAVE_ARGUMENT
FIXED_WIDTH_OPCODES = (3, 6, 0, "alpha", 2)
# deterministic pyc files (PEP 552), use hashes instead of mtime
DETERMINISTIC_PYC = (3, 7, 0, "alpha", 4)
# positional only parameters (PEP 570), affects marshal
POSITIONAL_ONLY_PARAMS = (3, 8, 0, "alpha", 1)
# makes annotations future default
ANNOTATIONS_IS_DEFAULT = (3, 10, 0, "alpha", 1)
# MAKE_FUNCTION annotation flag expects a tuple instead of dict
ANNOTATIONS_USES_TUPLE = (3, 10, 0, "alpha", 2)
# jump targets are instruction offsets instead of byte offsets
JUMP_BY_OFFSET = (3, 10, 0, "alpha", 7)
# annotations future is no longer default (lol)
ANNOTATIONS_IS_NOT_DEFAULT = (3, 10, 0, "beta", 1)

PYC_MAGIC_NUMBERS: dict[int, Version] = {
    3000: (3, 0, 0),
    3370: FIXED_WIDTH_OPCODES,
    3392: DETERMINISTIC_PYC,
    3410: POSITIONAL_ONLY_PARAMS,
    3430: ANNOTATIONS_IS_DEFAULT,
    3432: ANNOTATIONS_USES_TUPLE,
    3435: JUMP_BY_OFFSET,
    3437: ANNOTATIONS_IS_NOT_DEFAULT,
    3550: (3, 13, 0),  # reserved for 3.13
}

# 3rd and 4th bytes on a pyc file header
PYC_MAGIC = b"\r\n"

# digits can be either 30 or 15 bits long, but marshal always uses 15
LONG_SHIFT_RATIO = sys.int_info.bits_per_digit // 15


def fix_code_marshal(src: bytes, version: Version) -> bytes:
    code = bytearray(src)
    if version < POSITIONAL_ONLY_PARAMS:
        # TODO: implement a custom marshal function instead of this
        i = 0
        skips: list[int] = []
        while i < len(code):
            # l: LONG
            if skips:
                skips[-1] -= 1
                if skips[-1] == 0:
                    i += 4
                    skips.pop()
            t = chr(code[i] & ~0x80)
            if t == "c":  # code type
                code[i + 4 : i + 4] = bytes(4)
                i += 4 * 6
                skips.append(9)
            elif t == "g":  # float
                i += 8
            elif t == "y":  # complex
                i += 16
            elif t == "l":  # long integer
                n = int.from_bytes(code[i + 1 : i + 5], "little")
                i += 4
                if n != 0:
                    # hopefully correct equation simplification
                    i += 2 * ((n - 1) % LONG_SHIFT_RATIO + n)
            elif t in {"i", "r"}:  # i: int, r: reference
                i += 4
            elif t in {"z", "Z"}:  # short string
                i += code[i + 1] + 1
            elif t in {"a", "A", "s", "t", "u"}:  # string
                i += int.from_bytes(code[i + 1 : i + 5], "little") + 4
            elif t == ")":  # short tuple
                if skips:
                    skips[-1] += code[i + 1]
                i += 1
            elif t in {"0", "N", "F", "T", "S", "."}:  # singletons
                pass
            else:
                raise RuntimeError(
                    f"unexpected byte while patching pyc @ {i}: {code[i]:0>2x}"
                )
            i += 1

    return bytes(code)


def read_pyc(f: BinaryIO) -> tuple[Version, CodeType]:
    magic = int.from_bytes(f.read(2), "little")
    if magic not in range(3000, 4000):
        raise RuntimeError(f"unknown magic header: {magic} (not python 3?)")

    for k, v in PYC_MAGIC_NUMBERS.items():
        if magic <= k:
            break
        version = v

    if version < DETERMINISTIC_PYC:
        f.seek(12)
    else:
        f.seek(16)

    return version, marshal.loads(fix_code_marshal(f.read(), version))
