# Dependency audit

Run `uv run python scripts/license_audit.py`. It fails on any GPL, LGPL, AGPL or unknown licence. CI repeats it.

Result on 2026-10-30: 21 runtime packages and 33 with development tools, none flagged. `pathspec` (MPL-2.0) is a development-only dependency of mypy and is not redistributed.

Bundled native libraries inside wheels (for example libxml2 in lxml) were not individually audited.
