import contextlib
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

from release_fence import FenceError, Policy, diff, scan
from release_fence.cli import main
from release_fence.core import load_json


class FenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "release.zip"

    def archive(self, pairs=None, method=zipfile.ZIP_DEFLATED):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.path, "w", compression=method) as z:
                for name, data in pairs if pairs is not None else [("README.md", b"hello"), ("pkg/x.py", b"pass\n")]:
                    z.writestr(name, data)
        return self.path

    def patch(self, offset, fmt, value):
        raw = bytearray(self.path.read_bytes())
        struct.pack_into(fmt, raw, offset, value)
        self.path.write_bytes(raw)

    def test_inventory_hashes_order_total(self):
        result = scan(self.archive())
        self.assertEqual(result["total_bytes"], 10)
        self.assertEqual(result["files"][0], {"path": "README.md", "size": 5, "sha256": hashlib.sha256(b"hello").hexdigest()})
        self.assertEqual(result["violations"], [])
        self.assertEqual(scan(self.path), result)

    def test_stored_empty_and_directory(self):
        result = scan(self.archive([("dir/", b""), ("dir/a", b"")], zipfile.ZIP_STORED))
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["total_bytes"], 0)
        self.assertEqual(scan(self.archive([]))["files"], [])

    def test_order_and_timestamp_independent(self):
        first = scan(self.archive([("b", b"2"), ("a", b"1")]))
        second = scan(self.archive([("a", b"1"), ("b", b"2")]))
        self.assertEqual(first, second)

    def test_policy(self):
        result = scan(self.archive(), Policy(required=("LICENSE",), forbidden=("pkg/*",)))
        self.assertEqual(result["violations"], ["missing required path: LICENSE", "forbidden path: pkg/x.py"])
        self.assertEqual(scan(self.path, Policy(forbidden=("*.py",)))["violations"], ["forbidden path: pkg/x.py"])

    def test_limits(self):
        self.archive()
        for p in (Policy(max_files=1), Policy(max_member_bytes=4), Policy(max_total_bytes=9)):
            with self.subTest(p=p), self.assertRaises(FenceError):
                scan(self.path, p)

    def test_paths(self):
        for name in ("/a", "../a", "a/../b", "a//b", "./a", "a\\b", "C:a", "a\x01b"):
            with self.subTest(name=name), self.assertRaises(FenceError):
                scan(self.archive([(name, b"x")]))

    def test_duplicates_and_parent_files(self):
        for pairs in ([('a', b'x'), ('a', b'y')], [('a/', b''), ('a', b'x')], [('a', b'x'), ('a/b', b'y')]):
            with self.subTest(pairs=pairs), self.assertRaises(FenceError):
                scan(self.archive(pairs))

    def test_special_files(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFDIR):
            info = zipfile.ZipInfo('a')
            info.create_system = 3
            info.external_attr = (mode | 0o777) << 16
            with self.subTest(mode=mode), self.assertRaises(FenceError):
                scan(self.archive([(info, b'x')]))

    def test_directory_payload(self):
        with self.assertRaises(FenceError):
            scan(self.archive([('a/', b'x')]))

    def test_unsupported_compression_and_encryption(self):
        self.archive()
        central = self.path.read_bytes().index(b'PK\x01\x02')
        for field, value in ((10, 99), (8, 1)):
            self.archive()
            self.patch(central + field, '<H', value)
            with self.assertRaises(FenceError):
                scan(self.path)

    def test_crc_corruption(self):
        self.archive([('a', b'abc')], zipfile.ZIP_STORED)
        raw = bytearray(self.path.read_bytes())
        raw[31] ^= 1
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(FenceError, 'CRC'):
            scan(self.path)

    def test_structure_guards(self):
        self.archive()
        valid = self.path.read_bytes()
        for raw in (b'not zip', valid[:-1], valid + b'junk', b'junk' + valid):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw[:8]), self.assertRaises(FenceError):
                scan(self.path)
        for offset, fmt, value in ((-18, '<H', 1), (-12, '<H', 65535), (-10, '<I', 9000000), (-6, '<I', 0)):
            self.path.write_bytes(valid)
            self.patch(len(valid) + offset, fmt, value)
            with self.subTest(offset=offset), self.assertRaises(FenceError):
                scan(self.path)

    def test_local_header_mismatch(self):
        for offset, fmt, value in ((6, '<H', 1), (8, '<H', 99), (14, '<I', 0), (26, '<H', 60000)):
            self.archive()
            self.patch(offset, fmt, value)
            with self.subTest(offset=offset), self.assertRaises(FenceError):
                scan(self.path)

    def test_declared_size_does_not_hide_actual_bytes(self):
        self.archive([('a', b'x' * 100000)])
        central = self.path.read_bytes().index(b'PK\x01\x02')
        self.patch(22, '<I', 1)
        self.patch(central + 24, '<I', 1)
        with self.assertRaisesRegex(FenceError, 'actual uncompressed size'):
            scan(self.path, Policy(max_member_bytes=100))

    def test_data_descriptor(self):
        class Unseekable(io.BytesIO):
            def seekable(self):
                return False
            def seek(self, *args):
                raise io.UnsupportedOperation()
        stream = Unseekable()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('a', b'hello' * 100)
        self.path.write_bytes(stream.getvalue())
        self.assertEqual(scan(self.path)['total_bytes'], 500)

    def test_deflate_chunk_boundaries(self):
        for size in (65535, 65536, 65537, 131072, 131073):
            with self.subTest(size=size):
                result = scan(self.archive([('a', b'a' * size)]))
                self.assertEqual(result['total_bytes'], size)
                self.assertEqual(result['files'][0]['sha256'], hashlib.sha256(b'a' * size).hexdigest())

    def test_invalid_data_descriptor(self):
        class Unseekable(io.BytesIO):
            def seek(self, *args):
                raise io.UnsupportedOperation()
        output = Unseekable()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('a', b'a' * 65537)
        raw = bytearray(output.getvalue())
        self.path.write_bytes(raw)
        self.assertEqual(scan(self.path)['total_bytes'], 65537)
        offset = raw.index(b'PK\x07\x08')
        raw[offset + 4] ^= 1
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(FenceError, 'descriptor'):
            scan(self.path)

    def test_zip64_extra_and_malformed_extra(self):
        for extra in (b'\x01\x00\x00\x00', b'\x12\x12\xff\xff'):
            info = zipfile.ZipInfo('a')
            info.extra = extra
            with self.subTest(extra=extra), self.assertRaises(FenceError):
                scan(self.archive([(info, b'hello')]))

    def test_size_mismatch_without_limit(self):
        self.archive([('a', b'hello')])
        central = self.path.read_bytes().index(b'PK\x01\x02')
        self.patch(22, '<I', 1)
        self.patch(central + 24, '<I', 1)
        with self.assertRaisesRegex(FenceError, 'size mismatch'):
            scan(self.path)

    def test_nul_path_and_truncated_deflate(self):
        self.archive([('abc', b'hello' * 100)])
        raw = bytearray(self.path.read_bytes())
        central = raw.index(b'PK\x01\x02')
        raw[31] = raw[central + 47] = 0
        self.path.write_bytes(raw)
        with self.assertRaises(FenceError):
            scan(self.path)
        self.archive([('abc', b'hello' * 100)])
        raw = bytearray(self.path.read_bytes())
        central = raw.index(b'PK\x01\x02')
        size = struct.unpack_from('<I', raw, 18)[0]
        struct.pack_into('<I', raw, 18, size - 1)
        struct.pack_into('<I', raw, central + 20, size - 1)
        self.path.write_bytes(raw)
        with self.assertRaises(FenceError):
            scan(self.path)

    def test_policy_validation(self):
        for value in (None, [], {'unknown': 1}, {'max_files': True}, {'max_files': 0}, {'max_total_bytes': 2**40}, {'required': 'x'}, {'required': ['../a']}, {'required': ['\ud800']}, {'required': ['a', 'a']}, {'forbidden': [1]}):
            with self.subTest(value=value), self.assertRaises(FenceError):
                Policy.from_dict(value)

    def test_json_validation(self):
        path = self.root / 'input.json'
        for raw in (b'{"required":[],"required":[]}', b'{', b'NaN', b'Infinity', b'[' * 2000 + b']' * 2000, b'\xff'):
            path.write_bytes(raw)
            with self.subTest(raw=raw[:20]), self.assertRaises(FenceError):
                load_json(path)

    def test_diff(self):
        old = scan(self.archive([('a', b'1'), ('b', b'2')]))
        new = scan(self.archive([('b', b'3'), ('c', b'4')]))
        self.assertEqual(diff(old, new), {'added': ['c'], 'removed': ['a'], 'changed': ['b']})
        self.assertEqual(diff(old, old), {'added': [], 'removed': [], 'changed': []})

    def test_invalid_inventory(self):
        good = scan(self.archive())
        invalid = [{}, dict(good, schema_version=True), dict(good, total_bytes=9), dict(good, files=[{'path': '\ud800', 'size': 0, 'sha256': 'a'*64}]), dict(good, violations='bad')]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(FenceError):
                diff(value, good)

    def test_cli_status_and_output(self):
        self.archive()
        policy = self.root / 'policy.json'
        policy.write_text('{"required":["LICENSE"]}')
        for cmd, expected in ((['scan', str(self.path)], 0), (['check', str(self.path), '--policy', str(policy)], 1), (['scan', '/missing'], 2)):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main(cmd), expected)
            if expected == 2:
                self.assertEqual(out.getvalue(), '')
                self.assertIn('release-fence:', err.getvalue())
            else:
                json.loads(out.getvalue())

    def test_module_entrypoint(self):
        proc = subprocess.run([sys.executable, '-m', 'release_fence', '--help'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('Inspect ZIP', proc.stdout)


if __name__ == '__main__':
    unittest.main()
