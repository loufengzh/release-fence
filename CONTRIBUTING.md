# Contributing

Keep the runtime dependency-free and the ZIP-only scope explicit. Use synthetic,
small in-memory/generated fixtures, never confidential release archives. New
rules need positive and negative tests, deterministic output and documented exit
codes. Never add extraction or execution as a convenience feature.

Run `PYTHONPATH=src python -m unittest discover -s tests -v`. Changes to parsing
must include truncated/mismatched metadata coverage. Changes to inventory schema
must consider existing saved manifests. Update English docs and the three short
translated guides when user-visible behavior changes.

Report bugs with Python version, command, expected/actual result and a synthetic
reproducer. Do not attach credentials, private archives or personal data.
