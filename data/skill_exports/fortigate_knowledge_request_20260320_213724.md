# Knowledge Request — Fortigate Release Notes / Changelog
Generated: 2026-03-20 21:37 UTC

## What We Need
Release Notes / Changelog for Fortigate
Current detected version: 7.6.0


## Where to Find It
- https://docs.fortinet.com/document/fortigate/{version}/fortios-release-notes/

- https://fndn.fortinet.net/index.php?/fortiapi/
- https://docs.fortinet.com/document/fortigate/{version}/upgrade-guide/

## Why We Need It
These skills may need updating:
  - fortigate_system_status (uses /api/v2/monitor/system/status)

## How to Bring It Back
**Option A** — Download the PDF:
1. Download the document on an internet-connected machine
2. Copy the PDF to: `data/docs/` on the agent host
3. Run: `ingest_pdf("fortigate-changelog.pdf")`

**Option B** — Copy text content:
1. Copy the relevant section text
2. Save as a .txt file in `data/docs/`
3. Tell the agent to ingest it

After ingesting, run: `knowledge_ingest_changelog("fortigate")`
to extract any breaking changes from the document.
