# Knowledge Request — Proxmox API Documentation
Generated: 2026-03-20 21:41 UTC

## What We Need
API Documentation for Proxmox



## Where to Find It
- https://pve.proxmox.com/pve-docs/api-viewer/

- https://pve.proxmox.com/wiki/Roadmap
- https://pve.proxmox.com/wiki/Upgrade_from_{from_version}_to_{to_version}

## Why We Need It
These skills may need updating:
  - proxmox_vm_status (uses /api2/json/version)

## How to Bring It Back
**Option A** — Download the PDF:
1. Download the document on an internet-connected machine
2. Copy the PDF to: `data/docs/` on the agent host
3. Run: `ingest_pdf("proxmox-api_docs.pdf")`

**Option B** — Copy text content:
1. Copy the relevant section text
2. Save as a .txt file in `data/docs/`
3. Tell the agent to ingest it

After ingesting, run: `knowledge_ingest_changelog("proxmox")`
to extract any breaking changes from the document.
