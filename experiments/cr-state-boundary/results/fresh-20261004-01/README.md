# Fresh state-boundary trials

Baseline root commit: `11e78503586aae6d728d35bf2b875917583aaa3a`. The unchanged `campaign.py` was copied byte-for-byte into this isolated output root so it could write fresh logs without colliding with the original `smoke/` evidence. Its runtime and application artifacts resolve to the original, hash-pinned trial binaries.

- Fresh same-IP: `smoke/same/run-03` — PASS.
- Fresh changed-IP: `smoke/changed/run-01` — PASS.
- Both trials recorded ten consecutive pre- and post-restore application round trips.
- Same-IP first refresh: stored/probed `.3` / `.3`. Changed-IP first pre-mutation refresh: stored/probed `.3` / `.6`, followed by stored `.6`.
- The unchanged CLI requires three same-IP PASS JSON files before changed-IP. Prior same-IP runs 01 and 02 were copied byte-for-byte into this isolated gate directory; fresh run 03 supplied the third PASS. The changed-IP trial was then fresh.
- Exact commands, source/module revisions, source and artifact hashes, host/Docker topology, gate input hashes, logs, checkpoint boundaries, results, and per-file evidence checksums are in `provenance/` and the two `smoke/` trial directories.
- The campaign deletes PASS checkpoint image files after recording their checksums and inventory.

No experiment source or runner code was changed.
