# Workflow runbook

Use a unique run directory for every execution. Store the source plan, request IDs, status snapshots, and output checksums together. Retry a failed stage only after recording the previous error. Do not put keys or signed URLs in the run artifacts.

The submit stage calls `POST /v1/videos/generations`; polling and download use the same account key and request ID. Final assembly is local and should be reproducible from the reviewed plan.