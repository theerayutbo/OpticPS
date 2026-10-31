# Dependency audit

Run `uv run python scripts/license_audit.py`. It fails on any GPL, LGPL, AGPL or unknown licence. CI repeats it.

Re-run on 2026-10-31 (branch v1.3-mpam, a2eb969): 34 installed packages, 0 flagged, SBOM unchanged. Details and bundled-asset check: `docs/DEPENDENCY_EXCEPTIONS.md`.

Result on 2026-10-30: 21 runtime packages and 33 with development tools, none flagged. `pathspec` (MPL-2.0) is a development-only dependency of mypy and is not redistributed.

Bundled native libraries inside wheels (for example libxml2 in lxml) were not individually audited.

v1.2 adds `h5py` (BSD-3-Clause per its installed metadata) for HDF5 scope exports. Re-run: 34 installed packages, none flagged.
