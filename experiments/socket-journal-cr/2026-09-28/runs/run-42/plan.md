# run-42 SEDP recovery-path diagnostic

Corrected rerun of run-41. The run-41 preflight checked the new artifact hash,
but its Docker mount still pointed at the run-31 artifact. run-42 mounts the
new diagnostic artifact explicitly. No checkpoint/restore.
