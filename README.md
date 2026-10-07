# release-fence

A small, dependency-free packaging quality gate for ZIP releases. Answer two
questions before publishing: **did the archive include the files we promised,
and what content changed since the last release?**

[简体中文](docs/README.zh-CN.md) · [Русский](docs/README.ru.md) · [Deutsch](docs/README.de.md)

## Why use it?

An archive can build successfully while omitting `LICENSE`, shipping temporary
files, or unexpectedly growing. release-fence inventories the actual decompressed
file bytes, applies an explicit policy, and emits deterministic JSON suitable for
CI artifacts. It never extracts files, executes archive content, contacts the
network, or changes the input archive.

This is a **packaging quality tool**, not a malware scanner, secret detector,
signature verifier, or guarantee that arbitrary archives are safe. A matching
SHA-256 records content identity; it does not establish authenticity.

## Quick start

Requires Python 3.10+ with zlib support. The runtime uses only the standard library.
Install from this checkout (the distribution is not claimed to be on PyPI):

```sh
python -m pip install .
python examples/make_demo.py
release-fence check examples/demo.zip --policy examples/policy.json
release-fence scan examples/demo.zip > before.json
release-fence diff before.json before.json
```

The example generates only synthetic public text. `scan` and `check` accept the
same optional policy. Both print a complete inventory to stdout. `check` exits 1
for missing/forbidden paths; `scan` records those violations but exits 0, useful
when collecting evidence before deciding whether to gate. Incomplete scans never
print a partial inventory. The CLI sends errors to stderr.

| Exit | Meaning |
| --- | --- |
| 0 | Complete scan; check passed; or diff has no content changes |
| 1 | Check has policy violations; or diff found content changes |
| 2 | Invalid input, unsupported ZIP feature, resource limit, I/O or CLI error |

A size/count limit is exit 2, not 1: reading stops and no complete inventory exists.

## Explicit JSON policy

```json
{
  "required": ["README.md", "LICENSE"],
  "forbidden": ["*.pyc", "__pycache__/*", "*.tmp"],
  "max_files": 1000,
  "max_total_bytes": 67108864,
  "max_member_bytes": 16777216
}
```

- All fields are optional; the shown numeric values are defaults. Lists default
  to empty. Unknown keys, duplicate keys, duplicate rules, booleans as numbers,
  nonpositive limits and malformed JSON are errors.
- `required` means exact, case-sensitive relative **file** paths, not globs or
  directories. No implicit top-level directory stripping takes place.
- `forbidden` uses Python `fnmatch.fnmatchcase` against the entire canonical path,
  including directory entries with the final slash removed. `*` matches `/` and
  leading dots; `**` has no special recursive meaning. Patterns are case-sensitive
  on every OS. Use `*.pyc` for bytecode at any depth. Directory absence does not
  imply the absence of children; use `build` and `build/*` to cover both.
- Count limits cover regular files; the fixed 10,000-entry ceiling includes
  directories. Byte limits cover actual decompressed bytes, independently of
  declared sizes. Declarations exceeding a limit are rejected before decoding.
- Custom file limits may be at most 10,000; byte limits at most 1 GiB each. These
  are per invocation, not process-wide CPU/time or concurrent-memory budgets.

No built-in language profiles or inferred rules are applied. Review the example
policy for your own project rather than assuming it fits every release.

## Inventory and diff

```json
{
  "schema_version": 1,
  "files": [{"path": "README.md", "size": 5,
             "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"}],
  "total_bytes": 5,
  "violations": []
}
```

Records sort by path; hashes cover uncompressed file bytes. Timestamps, archive
names, compression, comments, permission bits, explicit empty directories and
member order do not affect file records or content diffs. Explicit directory
entries can affect forbidden-path violations. Renames appear as removed plus added.
`diff` validates both schema-1 inventories and prints sorted `added`, `removed`,
and `changed` path lists. Only file content/size affects the diff; policy violations
are deliberately not compared. Keep the original inventory if you need its gate
result. JSON output is ASCII-escaped and stable for identical inputs and policies.

```python
from release_fence import Policy, scan, diff
inventory = scan("release.zip", Policy(required=("LICENSE",)))
assert not inventory["violations"]
```

## Deliberately bounded ZIP support

- ZIP only, stored or raw-deflated members. No TAR, ZIP64, encryption, split disks,
  self-extracting prefixes, unsupported flags, or special files such as symlinks.
- Fixed archive ceiling: 64 MiB compressed/on-disk. Central directory: 8 MiB.
  JSON policy/inventory input: 8 MiB and nesting depth 64. Entry names: 4096 UTF-8
  bytes. Rule lists: at most 1000 strings, each at most 4096 characters.
- Rejects absolute/drive/backslash paths, control characters, empty path segments,
  `.`/`..`, duplicate file/directory paths and files used as parent directories.
  Unicode names remain exact: no Unicode normalization or case folding. Therefore
  this does not detect collisions on every potential extraction filesystem.
- Reads compressed and decompressed data in at most 64 KiB chunks, enforcing
  actual member/total limits. Checks CRC, decompressed length, deflate completion,
  data descriptors, local/central consistency and contiguous member spans.
- Conservative parser: rejects central digital signatures, extra/padding data,
  unrecognized flags and archive comments containing a later end-record signature.
  Some ZIPs accepted by other tools will be rejected. Rebuild a plain ZIP rather
  than loosening checks silently. Filename encoding is UTF-8 when flagged, CP437
  otherwise; Unicode-path extra fields do not rename inventory paths.

The input should remain unchanged during a run. There is no extraction target,
full ZIP conformance validator, sandbox, CPU deadline or streaming stdin mode.
For untrusted input, use separate OS resource limits and isolation appropriate to
your environment. See [design notes](docs/design.md).

## CI and development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m pip wheel --no-deps --no-build-isolation . -w dist
```

CI tests Python 3.10–3.13 on Linux and Python 3.12 on Windows and macOS. Each
job builds a wheel, installs it without network access in a clean temporary virtual
environment, and runs the full test suite outside the checkout against that wheel.
The installed CLI smoke covers Unicode archive member names, paths containing
spaces, case-sensitive forbidden rules, scan/check/diff output and exit codes
0/1/2. Tests create all fixtures locally; they require no network, external archive
samples or credentials. Preparing build tooling may require network access.

To repeat the installed-wheel check locally after building:

```sh
python .github/scripts/check_install.py dist/release_fence-0.1.0-py3-none-any.whl
```

MIT licensed. Contributions should include a small synthetic fixture, expected
exit code, and regression test. See [CONTRIBUTING.md](CONTRIBUTING.md).

JSON result output write or flush failures in `scan`, `check`, or `diff` return exit 2, including a full output device or a closed pipe. Output already written cannot be retracted; discard incomplete output after any I/O failure. Empty ZIPs may have a standard archive comment, but no unaccounted bytes before the end record.
