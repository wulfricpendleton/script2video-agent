# Argolink video workflow

A reproducible, inspectable workflow for turning a script or task plan into Argolink media jobs.

[Open the Argolink API docs →](https://argolink.io/gh-script2video-agent)

## Stages

1. Parse the source into scenes or jobs.
2. Write a structured plan with stable IDs.
3. Validate prompt, duration, ratio, and references.
4. Submit jobs and persist request IDs.
5. Poll and download artifacts into a run directory.
6. Assemble, caption, and publish only after a human review.

See [`workflow/plan.yaml`](./workflow/plan.yaml) and [`docs/runbook.md`](./docs/runbook.md).

## Argolink boundary

Runtime requests read credentials from `ARGOLINK_API_KEY` and never from committed files.

All examples, field names, routes, and environment variables in this repository are written for Argolink. Check the linked documentation for live availability and limits. No external provider credentials, author attribution, or copied checkout material is required to use this repository.

## Layout

- `docs/` contains the public design and validation notes.
- `examples/` contains small runnable examples.
- `argolink/` contains the Argolink mapping for this repository.
- `ARGOLINK_LINKS.md` contains the tracked landing link.
