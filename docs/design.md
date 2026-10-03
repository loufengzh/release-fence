# Design and boundaries

The core function returns one complete schema-1 dictionary or raises `FenceError`.
There is no partial-result mode. Required/forbidden checks run only after successful
inventory generation. This keeps a failed decoder from accidentally producing a
passing gate or a misleading diff.

Before creating `ZipFile`, the tool checks the end record and walks the bounded
central-directory records. `ZipFile` supplies decoded member metadata; a separate
bounded raw-deflate/stored reader hashes bytes. We intentionally do not rely on
`ZipExtFile`'s declared-size truncation when enforcing actual byte limits. Each
member must finish decoding, match its CRC and declared size, and occupy a
consistent, nonoverlapping local span. Data-descriptor records are checked.

Limits reduce resource surprises but do not promise constant memory, a wall-clock
bound, or suitability for an Internet upload endpoint. Metadata, JSON and results
are held in memory. The implementation processes inputs sequentially and does not
extract content, inspect executable semantics, or determine whether a file is
confidential. Required filenames do not validate their contents or legal meaning.

Schema 1 file records deliberately omit ZIP metadata and directories so repacking
the same regular-file bytes yields the same file records and content diff.
Explicit directory entries may still change forbidden-path policy violations. This is a content release
comparison, not a byte-for-byte ZIP comparator, SBOM, provenance attestation or
permission-mode audit. Expected fingerprints should be distributed through your
own authenticated channel.

Current limitations are intentional: no ZIP64, TAR, recursive archives, stdin,
user plugins or built-in language profiles. Any future format support needs its
own resource model, deterministic serialization contract and synthetic tests.
