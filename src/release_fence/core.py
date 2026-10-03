"""Bounded ZIP inspection using only the Python standard library."""
from dataclasses import dataclass
from fnmatch import fnmatchcase
import hashlib
import json
import os
import re
import stat
import struct
import zipfile
import zlib

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_CENTRAL = 8 * 1024 * 1024
MAX_ENTRIES = 10000
CHUNK = 64 * 1024


class FenceError(ValueError):
    """Invalid input or a resource bound prevented a complete inventory."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise FenceError(f"nonstandard JSON constant: {value}")


def load_json(path):
    with open(path, "rb") as stream:
        raw = stream.read(MAX_CENTRAL + 1)
    if len(raw) > MAX_CENTRAL:
        raise FenceError("JSON input exceeds 8 MiB")
    try:
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 64:
                raise FenceError("JSON nesting exceeds 64")
            children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
            pending.extend((child, depth + 1) for child in children)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise FenceError(f"invalid JSON: {exc}") from exc


def path_ok(name, directory=False):
    if not isinstance(name, str) or not name:
        return False
    try:
        if len(name.encode("utf-8")) > 4096:
            return False
    except UnicodeError:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in name) or "\\" in name or ":" in name:
        return False
    parts = (name[:-1] if directory and name.endswith("/") else name).split("/")
    return all(p not in ("", ".", "..") for p in parts)


@dataclass(frozen=True)
class Policy:
    required: tuple = ()
    forbidden: tuple = ()
    max_files: int = 1000
    max_total_bytes: int = 64 * 1024 * 1024
    max_member_bytes: int = 16 * 1024 * 1024

    def __post_init__(self):
        for key in ("max_files", "max_total_bytes", "max_member_bytes"):
            n = getattr(self, key)
            ceiling = MAX_ENTRIES if key == "max_files" else 1024 * 1024 * 1024
            if type(n) is not int or not 1 <= n <= ceiling:
                raise FenceError(f"{key} must be an integer from 1 to {ceiling}")
        for key in ("required", "forbidden"):
            values = getattr(self, key)
            if not isinstance(values, (tuple, list)) or len(values) > 1000:
                raise FenceError(f"{key} must be a list of at most 1000 strings")
            if any(not isinstance(v, str) or not v or len(v) > 4096 for v in values):
                raise FenceError(f"invalid {key} entry")
            if len(set(values)) != len(values):
                raise FenceError(f"duplicate {key} entry")
            if key == "required" and any(not path_ok(v) for v in values):
                raise FenceError("required paths must be relative canonical file paths")
            object.__setattr__(self, key, tuple(values))

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
            raise FenceError("policy must be an object with only documented keys")
        return cls(**value)


def _guard(stream):
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    if size > MAX_ARCHIVE or size < 22:
        raise FenceError("archive must be 22 bytes to 64 MiB")
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0 or len(tail) - pos < 22:
        raise FenceError("missing ZIP end record")
    end = tail[pos:pos + 22]
    _, disk, start_disk, count_disk, count, central_size, offset, comment = struct.unpack("<4s4H2IH", end)
    absolute = size - len(tail) + pos
    if pos + 22 + comment != len(tail):
        raise FenceError("trailing data or invalid ZIP comment")
    if disk or start_disk or count_disk != count:
        raise FenceError("split ZIP archives are unsupported")
    if count == 65535 or central_size == 0xffffffff or offset == 0xffffffff:
        raise FenceError("ZIP64 archives are unsupported")
    if count > MAX_ENTRIES or central_size > MAX_CENTRAL or offset + central_size != absolute:
        raise FenceError("invalid or oversized central directory")
    stream.seek(0)
    if stream.read(4) != (b"PK\x03\x04" if count else b"PK\x05\x06"):
        raise FenceError("prefixed/self-extracting archives are unsupported")
    # Validate every central record before ZipFile allocates its member list.
    stream.seek(offset)
    for _ in range(count):
        header = stream.read(46)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            raise FenceError("invalid central directory record")
        name_len, extra_len, comment_len, disk_start = struct.unpack_from("<4H", header, 28)
        if disk_start or struct.unpack_from("<I", header, 42)[0] == 0xffffffff:
            raise FenceError("split/ZIP64 entry unsupported")
        stream.seek(name_len + extra_len + comment_len, os.SEEK_CUR)
        if stream.tell() > absolute:
            raise FenceError("central directory record exceeds bounds")
    if stream.tell() != absolute:
        raise FenceError("central directory count/size mismatch")
    return offset, count


def _extra(raw):
    while raw:
        if len(raw) < 4:
            raise FenceError("truncated ZIP extra field")
        tag, size = struct.unpack_from("<HH", raw)
        if tag == 1:
            raise FenceError("ZIP64 extra fields are unsupported")
        if size > len(raw) - 4:
            raise FenceError("truncated ZIP extra payload")
        raw = raw[4 + size:]


def scan(path, policy=None):
    """Return deterministic file inventory; raise FenceError on incomplete input.

    Resource limits stop scanning rather than returning partial hashes.
    """
    policy = policy or Policy()
    if not isinstance(policy, Policy):
        raise FenceError("policy must be a Policy instance")
    try:
        with open(path, "rb") as stream:
            central, count = _guard(stream)
            with zipfile.ZipFile(stream) as archive:
                infos = archive.infolist()
                if len(infos) != count:
                    raise FenceError("entry count mismatch")
                if sum(not i.is_dir() for i in infos) > policy.max_files:
                    raise FenceError("file count exceeds policy")
                names, records, spans = set(), [], []
                total = 0
                for info in infos:
                    _extra(info.extra)
                    name = info.orig_filename
                    directory = info.is_dir()
                    if not path_ok(name, directory) or name != info.filename:
                        raise FenceError("noncanonical member path")
                    canonical = name.rstrip("/")
                    if canonical in names:
                        raise FenceError("duplicate file/directory path")
                    names.add(canonical)
                    kind = stat.S_IFMT(info.external_attr >> 16)
                    if kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG):
                        raise FenceError("special file or inconsistent directory type")
                    if info.flag_bits & ~0x808:
                        raise FenceError("encrypted or unsupported ZIP flags")
                    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        raise FenceError("unsupported compression method")
                    if info.file_size > policy.max_member_bytes or total + info.file_size > policy.max_total_bytes:
                        raise FenceError("declared uncompressed size exceeds policy")
                    if directory and info.file_size:
                        raise FenceError("directory contains data")
                    if info.header_offset < 0 or info.header_offset + 30 > central:
                        raise FenceError("invalid local header offset")
                    stream.seek(info.header_offset)
                    local = stream.read(30)
                    if local[:4] != b"PK\x03\x04":
                        raise FenceError("invalid local header")
                    flags, method = struct.unpack_from("<HH", local, 6)
                    if flags != info.flag_bits or method != info.compress_type:
                        raise FenceError("local/central header mismatch")
                    name_len, extra_len = struct.unpack_from("<HH", local, 26)
                    end = info.header_offset + 30 + name_len + extra_len + info.compress_size
                    if end > central:
                        raise FenceError("member data exceeds local section")
                    local_name = stream.read(name_len)
                    try:
                        decoded = local_name.decode("utf-8" if flags & 0x800 else "cp437")
                    except UnicodeError as exc:
                        raise FenceError("invalid local filename encoding") from exc
                    if decoded != name:
                        raise FenceError("local/central filename mismatch")
                    _extra(stream.read(extra_len))
                    if not flags & 8 and struct.unpack_from("<III", local, 14) != (info.CRC, info.compress_size, info.file_size):
                        raise FenceError("local/central size or CRC mismatch")
                    digest = hashlib.sha256()
                    actual = 0
                    crc = 0
                    remaining = info.compress_size
                    decoder = zlib.decompressobj(-15) if method == zipfile.ZIP_DEFLATED else None
                    while remaining:
                        compressed = stream.read(min(CHUNK, remaining))
                        if not compressed:
                            raise FenceError("truncated member data")
                        remaining -= len(compressed)
                        pending = compressed
                        while pending or (decoder is not None and not decoder.eof):
                            budget = min(CHUNK, policy.max_member_bytes - actual + 1,
                                         policy.max_total_bytes - total + 1)
                            if decoder:
                                chunk = decoder.decompress(pending, budget)
                                pending = decoder.unconsumed_tail
                                if decoder.unused_data:
                                    raise FenceError("trailing compressed data")
                            else:
                                chunk, pending = pending[:budget], pending[budget:]
                            if not chunk and not pending:
                                break
                            actual += len(chunk)
                            total += len(chunk)
                            if actual > policy.max_member_bytes or total > policy.max_total_bytes:
                                raise FenceError("actual uncompressed size exceeds policy")
                            digest.update(chunk)
                            crc = zlib.crc32(chunk, crc)
                    if decoder and not decoder.eof:
                        raise FenceError("incomplete deflate stream")
                    if crc != info.CRC:
                        raise FenceError("CRC mismatch")
                    if flags & 8:
                        descriptor = stream.read(4)
                        if descriptor == b"PK\x07\x08":
                            descriptor = stream.read(12)
                            end += 16
                        else:
                            descriptor += stream.read(8)
                            end += 12
                        if len(descriptor) != 12 or struct.unpack("<III", descriptor) != (info.CRC, info.compress_size, info.file_size):
                            raise FenceError("invalid data descriptor")
                    if end > central:
                        raise FenceError("member descriptor exceeds local section")
                    spans.append((info.header_offset, end))
                    if actual != info.file_size:
                        raise FenceError("uncompressed size mismatch")
                    if not directory:
                        records.append({"path": name, "size": actual, "sha256": digest.hexdigest()})
                        if len(records) > policy.max_files:
                            raise FenceError("file count exceeds policy")
                spans.sort()
                if spans and (spans[0][0] != 0 or spans[-1][1] != central or
                              any(a[1] != b[0] for a, b in zip(spans, spans[1:]))):
                    raise FenceError("overlapping members or unaccounted local bytes")
                files = {r["path"] for r in records}
                if any("/".join(n.split("/")[:i]) in files for n in names for i in range(1, len(n.split("/")))):
                    raise FenceError("file used as a parent directory")
                violations = [f"missing required path: {p}" for p in sorted(policy.required) if p not in files]
                violations += [f"forbidden path: {p}" for p in sorted(names)
                               if any(fnmatchcase(p, pattern) for pattern in policy.forbidden)]
                return {"schema_version": 1, "files": sorted(records, key=lambda r: r["path"]),
                        "total_bytes": total, "violations": violations}
    except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error, UnicodeError, struct.error) as exc:
        raise FenceError(f"cannot inspect ZIP: {exc}") from exc


def _manifest(value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "files", "total_bytes", "violations"}:
        raise FenceError("invalid inventory keys")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise FenceError("unsupported inventory schema")
    if not isinstance(value["files"], list) or len(value["files"]) > MAX_ENTRIES:
        raise FenceError("invalid inventory files")
    result = {}
    for r in value["files"]:
        if not isinstance(r, dict) or set(r) != {"path", "size", "sha256"}:
            raise FenceError("invalid file record")
        if not path_ok(r["path"]) or r["path"] in result or type(r["size"]) is not int or r["size"] < 0:
            raise FenceError("invalid file path/size")
        if not isinstance(r["sha256"], str) or re.fullmatch("[0-9a-f]{64}", r["sha256"]) is None:
            raise FenceError("invalid SHA-256")
        result[r["path"]] = r
    if type(value["total_bytes"]) is not int or value["total_bytes"] != sum(r["size"] for r in result.values()):
        raise FenceError("invalid inventory total")
    if not isinstance(value["violations"], list) or any(not isinstance(v, str) for v in value["violations"]):
        raise FenceError("invalid violations")
    return result


def diff(before, after):
    """Compare validated inventories by content and size, ignoring ZIP metadata."""
    old, new = _manifest(before), _manifest(after)
    return {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
            "changed": sorted(p for p in old.keys() & new.keys() if old[p] != new[p])}
