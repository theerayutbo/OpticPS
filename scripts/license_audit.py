"""Audit licences of every installed distribution and fail on copyleft runtime dependencies."""
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import re
import sys
from importlib import metadata
from pathlib import Path

DENY = re.compile(r"\b(A?L?GPL|GNU (Lesser |Affero )?General Public)", re.I)


def licence_of(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [
        c.split("::")[-1].strip()
        for c in (meta.get_all("Classifier") or [])
        if c.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    return (meta.get("License") or "UNKNOWN").splitlines()[0][:80]


def main() -> int:
    rows = sorted(
        (
            {
                "name": d.metadata["Name"],
                "version": d.version,
                "license": licence_of(d),
            }
            for d in metadata.distributions()
        ),
        key=lambda r: r["name"].lower(),
    )
    Path("docs").mkdir(exist_ok=True)
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"name": "opticps", "type": "library"}},
        "components": [
            {
                "type": "library",
                "name": r["name"],
                "version": r["version"],
                "licenses": [{"expression": r["license"]}],
            }
            for r in rows
        ],
    }
    Path("docs/sbom.cdx.json").write_text(json.dumps(sbom, indent=2) + "\n")
    bad = [r for r in rows if DENY.search(r["license"]) or r["license"] == "UNKNOWN"]
    for r in rows:
        print(f"{r['name']:<24}{r['version']:<14}{r['license']}")
    print(f"\n{len(rows)} packages; flagged: {len(bad)}")
    for r in bad:
        print("FLAGGED", r)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
