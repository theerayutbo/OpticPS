# Aria checkpoint

Mode A. Aria: Opus, plans and gates. Fable is not used as a worker (user instruction, 2026-10-30).
Tip: b8e96fd on main.

Order: v1.0 released; v1.1 G.652; v1.2 UXR. Each gets a tag only after its gate.

| Unit | Dev | Loki | State |
|---|---|---|---|
| v1.0 | Opus | Sonnet | PASS. Tag v1.0.0 at 52e4fb3, CI green |
| v1.1 | Sonnet | Opus | PASS at cd443f9, merged |
| v1.2 | Sonnet | Opus | PASS at 870d3cd, text fixes 2b8eaad, merged |

Decisions: Grok headless with auto-approve was denied by the harness; Grok read-only returned no output, so it is not used. Fable is not used as a worker. Official M8100 and UXR guides obtained; UXR SCPI can now be documented, verified by page. Local extractions in the scratchpad, never committed.

NEXT ACTION: tag v1.2.0 after CI, then rename folder.
