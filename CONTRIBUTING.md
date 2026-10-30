# Contributing

Setup: `uv sync`. Checks: `uv run pytest`, `uv run ruff check src tests`, `uv run mypy`.

Rules:
- Write original code from published methods, and add the source to `docs/ALGORITHM_PROVENANCE.md`. Do not copy from other projects, including those named in `docs/CLEAN_ROOM_DECLARATION.md`.
- New dependencies need a permissive licence and must pass `scripts/license_audit.py`.
- Never commit private measurements, credentials or unpublished confidential data. `data/private/` is ignored for this reason.
- Never add SCPI that is not in official Keysight documentation for the confirmed model. Never add automatic output enabling.
- Label results simulated or measured. Record work in `docs/engineering_log/`.
- Contributions are accepted under the MIT licence.
