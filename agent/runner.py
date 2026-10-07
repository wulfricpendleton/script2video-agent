"""Responses-tool-loop script-to-video agent with explicit human review boundaries."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

VIDEO_BASE = "https://argolink.io/v1"
RESPONSES_BASE = "https://argolink.io/v1"
VIDEO_UA = "script2video-agent/1.0"
RESPONSES_UA = "script2video-agent-responses/1.0"
VIDEO_RATES = {"seedance-2.5": {"480p": 0.0874, "720p": 0.196, "1080p": 0.483},
               "seedance-2.0": {"480p": 0.053, "720p": 0.11, "1080p": 0.28, "4k": 0.58}}
STATUSES = {"pending", "done", "failed", "expired"}


class AgentError(RuntimeError):
    pass


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".state-", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _https(value: str, field: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{field} must be an HTTPS URL without credentials")
    return value


def parse_script(path: Path) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    if not lines:
        raise ValueError("script has no non-empty shots")
    return [{"id": f"shot-{index:02d}", "prompt": text, "model": "seedance-2.5",
             "duration": 5, "resolution": "720p", "aspect_ratio": "16:9",
             "references": [], "approved": False}
            for index, text in enumerate(lines, 1)]


def budget(plan: List[Dict[str, Any]], response_input_tokens: int = 0, response_output_tokens: int = 0) -> Dict[str, float]:
    video = sum(VIDEO_RATES.get(row["model"], {}).get(row["resolution"], 0) * row["duration"] for row in plan)
    # gpt-6-sol effective catalog rate: $0.60/M input and $3/M output.
    planner = response_input_tokens * 0.60 / 1_000_000 + response_output_tokens * 3.0 / 1_000_000
    return {"video_usd": round(video, 4), "planner_usd": round(planner, 6),
            "total_usd": round(video + planner, 6)}


class HTTPClient:
    def __init__(self, key: Optional[str], base: str, user_agent: str, opener: Optional[Callable[..., Any]] = None):
        self.key = key
        self.base = base.rstrip("/")
        self.user_agent = user_agent
        self._open = opener or urllib.request.urlopen
        parsed = urllib.parse.urlparse(self.base)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("production base URLs must use HTTPS; HTTP is allowed only for localhost tests")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base URL cannot contain credentials or query parameters")

    def call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None, *, binary: bool = False) -> Any:
        if not self.key:
            raise AgentError("API key is missing from the host environment")
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.key}", "User-Agent": self.user_agent}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            response = self._open(request, timeout=90)
            try:
                raw = response.read()
            finally:
                response.close()
        except urllib.error.HTTPError as error:
            detail = error.read(4096).decode("utf-8", errors="replace").replace(self.key, "[redacted]")
            raise AgentError(f"{method} {path} HTTP {error.code}: {detail[:400]}") from None
        if binary:
            return raw
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AgentError(f"{method} {path} returned invalid JSON") from error
        if not isinstance(result, dict):
            raise AgentError(f"{method} {path} returned a non-object")
        return result


class VideoClient(HTTPClient):
    def __init__(self, key: Optional[str] = None, base: Optional[str] = None, opener: Optional[Callable[..., Any]] = None):
        super().__init__(key or os.environ.get("VIDEO_API_KEY"), base or os.environ.get("VIDEO_API_BASE_URL") or VIDEO_BASE, VIDEO_UA, opener)

    def submit(self, shot: Dict[str, Any]) -> str:
        model = shot["model"]
        if model not in VIDEO_RATES or shot["resolution"] not in VIDEO_RATES[model]:
            raise AgentError(f"unsupported model/resolution: {model}/{shot['resolution']}")
        body = {key: shot[key] for key in ("model", "prompt", "duration", "resolution", "aspect_ratio")}
        body["generate_audio"] = True
        if shot.get("references"):
            body["reference_images"] = [{"url": _https(url, "reference")} for url in shot["references"]]
        result = self.call("POST", "/videos/generations", body)
        request_id = result.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise AgentError("video response did not include request_id")
        return request_id

    def status(self, request_id: str) -> Dict[str, Any]:
        if not isinstance(request_id, str) or not request_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid request_id")
        result = self.call("GET", f"/videos/{request_id}")
        if result.get("status") not in STATUSES:
            raise AgentError(f"unknown video status: {result.get('status')!r}")
        return result

    def download(self, request_id: str, path: Path) -> None:
        if path.exists():
            raise FileExistsError(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = self.call("GET", f"/videos/{request_id}/content", binary=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".video-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class ResponsesClient(HTTPClient):
    def __init__(self, key: Optional[str] = None, base: Optional[str] = None, opener: Optional[Callable[..., Any]] = None):
        super().__init__(key or os.environ.get("MODEL_API_KEY"), base or os.environ.get("MODEL_API_BASE_URL") or RESPONSES_BASE, RESPONSES_UA, opener)

    def create(self, input_items: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.call("POST", "/responses", {
            "model": "gpt-6-sol",
            "input": input_items,
            "tools": tools,
            "tool_choice": "auto",
        })


def tool_specs() -> List[Dict[str, Any]]:
    return [
        {"type": "function", "name": "plan_shots", "description": "Validate and save a shot plan before any video request.",
         "parameters": {"type": "object", "properties": {"shots": {"type": "array", "items": {"type": "object"}},
                                                          "reason": {"type": "string"}}, "required": ["shots", "reason"]}},
        {"type": "function", "name": "submit_video", "description": "Submit one approved shot exactly once and return request_id.",
         "parameters": {"type": "object", "properties": {"shot_id": {"type": "string"}, "prompt": {"type": "string"},
                                                          "model": {"type": "string"}, "duration": {"type": "integer"},
                                                          "resolution": {"type": "string"}, "aspect_ratio": {"type": "string"}},
                        "required": ["shot_id", "prompt", "model", "duration", "resolution", "aspect_ratio"]}},
        {"type": "function", "name": "inspect_video", "description": "Read one video status without submitting another job.",
         "parameters": {"type": "object", "properties": {"shot_id": {"type": "string"}}, "required": ["shot_id"]}},
        {"type": "function", "name": "approve_shot", "description": "Record a human review decision for a terminal video.",
         "parameters": {"type": "object", "properties": {"shot_id": {"type": "string"}, "decision": {"type": "string"},
                                                          "note": {"type": "string"}}, "required": ["shot_id", "decision", "note"]}},
    ]


@dataclass
class ScriptAgent:
    state_path: Path
    video: VideoClient
    max_revisions: int = 1

    def __post_init__(self) -> None:
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {"shots": {}, "revisions": {}}

    def save(self) -> None:
        atomic_json(self.state_path, self.state)

    def _shot(self, shot_id: str) -> Dict[str, Any]:
        if shot_id not in self.state["shots"]:
            raise AgentError(f"unknown shot_id: {shot_id}")
        return self.state["shots"][shot_id]

    def plan_shots(self, shots: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
        if not isinstance(shots, list) or not shots or not reason.strip():
            raise ValueError("plan_shots requires a non-empty list and reason")
        for shot in shots:
            if not isinstance(shot, dict) or not shot.get("id") or not shot.get("prompt"):
                raise ValueError("every shot needs id and prompt")
            shot.setdefault("model", "seedance-2.5")
            shot.setdefault("duration", 5)
            shot.setdefault("resolution", "720p")
            shot.setdefault("aspect_ratio", "16:9")
            shot.setdefault("references", [])
            if shot["model"] not in VIDEO_RATES or shot["resolution"] not in VIDEO_RATES[shot["model"]] or shot["duration"] not in range(4, 31):
                raise ValueError("shot model or duration is unsupported")
            self.state["shots"].setdefault(shot["id"], {**shot, "status": "planned", "revisions": 0})
        self.state["planning_reason"] = reason
        self.save()
        return {"status": "planned", "shot_ids": list(self.state["shots"])}

    def submit_video(self, shot_id: str, **changes: Any) -> Dict[str, Any]:
        shot = self._shot(shot_id)
        if shot.get("request_id"):
            raise AgentError("this shot already has a request_id; inspect it instead of resubmitting")
        if not shot.get("approved_for_submit"):
            raise AgentError("a human must approve the planned shot before submit_video")
        body = {**shot, **changes}
        request_id = self.video.submit(body)
        shot.update({key: body[key] for key in ("prompt", "model", "duration", "resolution", "aspect_ratio")})
        shot["request_id"] = request_id
        shot["status"] = "pending"
        self.save()
        return {"shot_id": shot_id, "request_id": request_id, "status": "pending"}

    def inspect_video(self, shot_id: str) -> Dict[str, Any]:
        shot = self._shot(shot_id)
        if not shot.get("request_id"):
            raise AgentError("shot has not been submitted")
        provider = self.video.status(shot["request_id"])
        shot["status"] = provider["status"]
        shot["provider"] = provider
        self.save()
        return {"shot_id": shot_id, **provider}

    def approve_shot(self, shot_id: str, decision: str, note: str) -> Dict[str, Any]:
        shot = self._shot(shot_id)
        if not note.strip() or decision not in {"submit", "accept", "revise", "stop"}:
            raise ValueError("decision must be submit, accept, revise, or stop, with a note")
        if decision == "revise":
            shot["revisions"] = shot.get("revisions", 0) + 1
            if shot["revisions"] > self.max_revisions:
                raise AgentError("revision budget exhausted")
        if decision == "submit":
            shot["approved_for_submit"] = True
        shot.setdefault("reviews", []).append({"decision": decision, "note": note})
        self.save()
        return {"shot_id": shot_id, "decision": decision, "status": shot.get("status", "planned")}

    def dispatch(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "plan_shots":
            return self.plan_shots(arguments["shots"], arguments["reason"])
        if name == "submit_video":
            shot_id = arguments.pop("shot_id")
            return self.submit_video(shot_id, **arguments)
        if name == "inspect_video":
            return self.inspect_video(arguments["shot_id"])
        if name == "approve_shot":
            return self.approve_shot(arguments["shot_id"], arguments["decision"], arguments["note"])
        raise AgentError(f"tool is not allow-listed: {name}")

    def responses_loop(self, planner: ResponsesClient, script: str, max_turns: int = 12) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = [{"role": "user", "content": [{"type": "input_text", "text": script}]}]
        for _ in range(max_turns):
            response = planner.create(items, tool_specs())
            calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
            if not calls:
                return response
            items.extend(calls)
            for call in calls:
                try:
                    arguments = json.loads(call.get("arguments", "{}"))
                    result = self.dispatch(call["name"], arguments)
                except (ValueError, KeyError, AgentError) as error:
                    result = {"error": str(error)}
                items.append({"type": "function_call_output", "call_id": call["call_id"],
                              "output": json.dumps(result, ensure_ascii=False)})
        raise AgentError("Responses tool loop exceeded its turn budget")


def main() -> int:
    parser = argparse.ArgumentParser(description="Responses-driven script-to-video workflow")
    parser.add_argument("script", type=Path)
    parser.add_argument("--out", type=Path, default=Path("plan.json"))
    parser.add_argument("--state", type=Path, default=Path(".agent/state.json"))
    parser.add_argument("--responses", action="store_true", help="run the authenticated gpt-6-sol tool loop")
    args = parser.parse_args()
    plan = parse_script(args.script)
    atomic_json(args.out, {"shots": plan, "budget": budget(plan)})
    if args.responses:
        agent = ScriptAgent(args.state, VideoClient())
        agent.responses_loop(ResponsesClient(), args.script.read_text(encoding="utf-8"))
    print(json.dumps({"shots": len(plan), "budget": budget(plan)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
