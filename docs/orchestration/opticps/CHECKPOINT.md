# Aria checkpoint

Mode A. Aria: Opus, plans and gates. Fable is not used as a worker (user instruction, 2026-10-30).
Tip: b8e96fd on main.

Order: v1.0 released; v1.1 G.652; v1.2 UXR. Each gets a tag only after its gate.

| Unit | Dev | Loki | State |
|---|---|---|---|
| v1.0 | Opus | Sonnet | PASS. Tag v1.0.0 at 52e4fb3, CI green |
| v1.1 | Sonnet, ../OpticPS-v11 | Opus | Dev running |
| v1.2 | Sonnet, ../OpticPS-v12 | Opus | First review FAIL at 44ce954; rework running |

Decisions: Grok headless with auto-approve was denied by the harness; Grok read-only returned no output, so it is not used. Fable is not used as a worker. Official M8100 and UXR guides obtained; UXR SCPI can now be documented, verified by page. Local extractions in the scratchpad, never committed.

NEXT ACTION: on v1.1 handoff, spawn Opus Loki. Merge v1.1, then rebase v1.2, re-review, merge, release. Then rename the folder to OpticPS.
