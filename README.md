# Script-to-video agent workflow

**Seedance 2.5 is available through [ArgoLink](https://argolink.io/gh-script2video-agent).** This repository is an inspectable agent pattern: a planner turns a text script into shot records, a model-facing runner submits one video job per approved shot, and a reviewer decides whether to retry. It is distinct from a fixed CLI because the planner can be replaced by a Responses tool loop. Last checked: 2026-10-07.

## Contract

The unit of work is a shot with an ID, prompt, model, duration, and reference manifest. A planner must not submit. The executor persists the request ID before polling and downloads only after the provider reports done. A timeout after POST is an unknown outcome, so the agent asks for an ID or operator review rather than issuing a second paid request. The review tool receives status, error, and a local media path; it can accept, revise the prompt, or stop.

A production agent should call a chat model through POST /v1/responses with tools named plan_shots, submit_video, inspect_video, and approve_shot. The schemas in the tool layer should require a stable shot ID and forbid the agent from changing a completed shot without an explicit revision. This repository keeps the video request helper small so the side effects remain auditable.

## Local preview

Run python3 agent/runner.py examples/plan.txt --out plan.json. The command only writes a plan and prints an output-second estimate; it does not call a model. The submit method is separately testable with a mocked urlopen. The neutral key is MODEL_API_KEY and the default base is https://argolink.io/v1.

## Agent safeguards

Limit planning iterations to three, video revisions to one per approved shot, and total budget to the operator's worksheet. A revision must point to the failed shot ID and preserve the prior response. Reject empty prompts, unknown models, and an output that is not a video file. Keep a human checkpoint before the first POST and before a revision. Parallel shots need an explicit semaphore and account limit; the sample deliberately runs no network calls in tests.

## Cost and model facts

The checked 720p Seedance 2.5 effective rate is $0.196 per output second. The three five-second example shots would estimate $2.94, excluding reference-video input and failed-job rules. The current model page is authoritative for 4–30 second duration, resolutions, reference limits, and billing. Failed, rejected, and expired jobs are not charged under the service contract. This estimate is not a measured invoice.

## FAQ

**Is the planner a chat model?** No; it is deterministic. Connect a Responses-compatible chat planner only after reviewing its tool schemas. **Can the agent retry?** It can request a new shot after a terminal failure, never after an unknown POST result. **Where are clips joined?** Keep assembly in a separate ffmpeg step so a generation failure is visible. **Can I use another video model?** Change the model and revalidate its own page; the request helper is intentionally not a universal adapter.
