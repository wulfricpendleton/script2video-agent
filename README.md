# Script-to-video agent workflow

This repository is an inspectable agent pattern for turning a text script into reviewed video shots. GPT-6 Sol receives a Responses API tool schema, plans stable shot records, asks for a human submit decision, and calls a Seedance video endpoint one shot at a time. The state file keeps every request ID and review note. The repository is independent of OpenAI, ByteDance and the service provider.

[Open the Seedance 2.5 model page](https://argolink.io/en/models/seedance-2.5) for the current video contract and [open the GPT-6 Sol model page](https://argolink.io/en/models/gpt-6-sol) for the current planner price. ArgoLink is one compatible API host; model and billing facts are checked before a run. Last checked: 2026-10-07.

## Why this differs from a fixed CLI

A fixed CLI maps an input line to one request. This workflow gives a planner tools and a review boundary:

1. The planner proposes shot IDs, prompts, model, duration, resolution and ratio.
2. plan_shots validates and saves that proposal without a network call.
3. A human uses approve_shot with decision submit, revise, accept or stop.
4. submit_video sends one POST for an approved shot and persists request_id immediately.
5. inspect_video reads one status. The agent does not hide a polling loop.
6. A separate operator can download content only after done and assemble it in an editor or ffmpeg step.

A request that timed out after POST is ambiguous. The agent refuses a second submit when a request_id exists, and keeps the provider response beside the shot.

## Install

The implementation uses Python's standard library.

~~~sh
git clone https://github.com/YOUR_ACCOUNT/script2video-agent
cd script2video-agent
python3 -m venv .venv
. .venv/bin/activate
~~~

To create an offline plan from one line per shot:

~~~sh
python -m agent.runner examples/plan.txt --out plan.json
~~~

The command writes stable IDs, defaults to Seedance 2.5 at 720p and prints an output-only estimate. It never loads a key. The sample plan contains three five-second shots, so its estimate is 2.94 USD at the current effective 720p rate.

## Responses planner tool loop

The authenticated mode is explicit:

~~~sh
export MODEL_API_KEY='planner-key-from-a-secret-store'
export VIDEO_API_KEY='video-key-from-a-secret-store'
python -m agent.runner examples/plan.txt \
  --out plan.json --state .agent/state.json --responses
~~~

The planner request is POST /v1/responses with model gpt-6-sol, input text and four function tools. The response is read for function_call items; each call is validated and dispatched through an allow-list. The loop sends function_call_output items back to Responses until the planner returns an ordinary message or twelve turns are reached.

The tool schemas are in agent/runner.py:

| Tool | Side effect | Required behavior |
| --- | --- | --- |
| plan_shots | writes local state | stable shot ID, prompt and model fields |
| approve_shot | writes a review note | submit, revise, accept or stop |
| submit_video | one billable POST | only an approved shot without request_id |
| inspect_video | one status GET | pending, done, failed or expired |

The planner cannot call arbitrary Python or invent an HTTP path. The video tool only sends model, prompt, duration, resolution, ratio and HTTPS reference images. Reference uploads are deliberately outside this minimal agent; upload them first through the documented media ticket flow and pass the resulting URL.

## Exact video lifecycle

The video client uses https://argolink.io/v1 and sends a descriptive User-Agent on every request. For a shot it sends:

~~~sh
BASE=https://argolink.io/v1
JOB=$(curl --fail-with-body -sS "$BASE/videos/generations" \
  -H "Authorization: Bearer $VIDEO_API_KEY" \
  -H "User-Agent: script2video-agent/1.0" \
  -H "Content-Type: application/json" \
  -d '{"model":"seedance-2.5","prompt":"A courier enters a quiet station at dawn","duration":5,"resolution":"720p","aspect_ratio":"16:9","generate_audio":true}')
ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["request_id"])' <<< "$JOB")
curl --fail-with-body -sS "$BASE/videos/$ID" \
  -H "Authorization: Bearer $VIDEO_API_KEY" -H "User-Agent: script2video-agent/1.0"
curl --fail-with-body -sS "$BASE/videos/$ID/content" \
  -H "Authorization: Bearer $VIDEO_API_KEY" -H "User-Agent: script2video-agent/1.0" \
  -o output/shot-01.mp4
~~~

Run the third GET only after status is done. The provider status contract is pending, done, failed and expired. A 409 content-not-ready or 424 failed response is retained, not hidden. This repository does not claim that it can cancel or refund a request.

The Python equivalent is VideoClient.submit, VideoClient.status and VideoClient.download. All generated files should be written beneath an operator-owned output directory, and downloads refuse to overwrite an existing path. Use ffmpeg after reviewing every clip; generation and editorial assembly remain separate failure domains.

## Planning a script

The input file is intentionally simple:

~~~text
A courier enters a quiet station at dawn.
The courier reads a blue envelope beside a window.
The camera follows the courier into the rain.
~~~

A real planner can replace this deterministic parser with a Responses call, but it must preserve:

- one immutable scene ID per proposed shot;
- an explicit prompt that names action, camera and continuity;
- a model ID present in the live catalog;
- duration and resolution supported by that model;
- reference URLs with HTTPS and no embedded credentials;
- a human decision before the first billable request.

The agent stores a revision count and allows one revision per shot by default. A revision must point to the shot ID and retain the earlier provider result. It cannot rewrite a completed shot in place.

## Cost accounting

The effective Seedance 2.5 rates checked on 2026-10-07 are 0.0874 USD/s at 480p, 0.196 at 720p and 0.483 at 1080p. Seedance 2.0 is 0.053, 0.11, 0.28 and 0.58 USD/s at 480p, 720p, 1080p and 4k. The planner model gpt-6-sol is 0.60 USD per million input tokens and 3.00 USD per million output tokens on the same catalog. The budget function records video output estimate plus planner token estimate; it does not guess reference-video seconds, retries, cache discounts or a bill.

For the three sample shots, 15 seconds at 720p Seedance 2.5 estimates 2.94 USD. If the planner used 20,000 input and 5,000 output tokens, its effective estimate would add 0.027 USD. Keep those columns separate in a run report so a rejected storyboard can be distinguished from a paid video.

Failed, rejected and expired jobs are not charged under the model contract, while a provider-accepted POST remains a request even if a local process disappears. Inspect the state file and account history before retrying.

## Safety and failure table

| Situation | Agent action |
| --- | --- |
| Empty prompt or unsupported duration | reject before HTTP |
| Missing key | fail with a local configuration error |
| 400/401/402/404 | surface response body and shot ID |
| 409 content not ready | keep request ID; inspect later |
| 424 failed job | preserve terminal error; human decides |
| 429/503 | honor provider retry guidance outside the tool loop |
| POST timeout with no ID | stop and investigate; never blind-resubmit |

Keys are read only from environment variables. Error text redacts the configured key. Do not put keys, private media URLs or planner transcripts in a public repository.

## Development

~~~sh
python -m unittest discover -s tests -v
python -m py_compile agent/runner.py
~~~

Tests use local fake HTTP responses and a fake Responses planner. They verify tool allow-listing, stable shot IDs, model and duration validation, API/User-Agent headers, request-ID persistence and the pending/done/failed/expired boundary. No production endpoint is contacted and no billable request is created.
