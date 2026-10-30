# Failures, dead ends and wrong assumptions

## X-001 Programming Guide could not be obtained
- What happened: `curl` of the Keysight URL returned HTML, not a PDF. The first request used a browser User-Agent. A second attempt with a browser User-Agent and alternate URLs was denied by the harness as bot-check circumvention.
- Handling: that approach was abandoned. WebFetch of the URL returned only a landing page with metadata (M8100-91B50, 2026-03-01).
- Consequence: CSV rules and `:TRAC:IMP` syntax are user-supplied, not read from the guide.
- To resolve: user supplies the PDF, then update VERIFICATION.md.

## X-002 pdftoppm missing
- The Read tool cannot render PDFs here. Text was extracted with pypdf in a throwaway uv environment.
