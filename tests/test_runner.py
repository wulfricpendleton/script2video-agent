import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from agent.runner import AgentError, ResponsesClient, ScriptAgent, VideoClient, budget, parse_script


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def read(self):
        return self.payload
    def close(self):
        pass


class Recorder:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []
    def __call__(self, request, timeout):
        self.requests.append(request)
        return FakeResponse(self.payloads.pop(0))


class RunnerTests(unittest.TestCase):
    def test_plan_parser_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "script.txt"
            path.write_text("# shot list\nA courier enters.\nThe courier waits.\n")
            plan = parse_script(path)
        self.assertEqual(plan[0]["id"], "shot-01")
        self.assertEqual(budget(plan)["video_usd"], 1.96)

    def test_video_submit_headers_and_request_id(self):
        recorder = Recorder([b'{"request_id":"job-1"}'])
        client = VideoClient("secret", base="https://api.test/v1", opener=recorder)
        shot = {"model": "seedance-2.5", "prompt": "x", "duration": 5,
                "resolution": "720p", "aspect_ratio": "16:9", "references": []}
        self.assertEqual(client.submit(shot), "job-1")
        self.assertEqual(recorder.requests[0].get_header("Authorization"), "Bearer secret")
        self.assertEqual(recorder.requests[0].get_header("User-agent"), "script2video-agent/1.0")

    def test_agent_requires_human_submit_and_persists_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            recorder = Recorder([b'{"request_id":"job-1"}'])
            video = VideoClient("secret", base="https://api.test/v1", opener=recorder)
            agent = ScriptAgent(root / "state.json", video)
            shot = {"id": "shot-01", "prompt": "x", "model": "seedance-2.5",
                    "duration": 5, "resolution": "720p", "aspect_ratio": "16:9"}
            agent.plan_shots([shot], "three-shot draft")
            with self.assertRaises(AgentError):
                agent.submit_video("shot-01")
            agent.approve_shot("shot-01", "submit", "human reviewed the storyboard")
            result = agent.submit_video("shot-01")
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(result["request_id"], "job-1")
            self.assertEqual(state["shots"]["shot-01"]["request_id"], "job-1")

    def test_responses_client_sends_model_and_tool_list(self):
        recorder = Recorder([b'{"output":[]}'])
        client = ResponsesClient("secret", base="https://api.test/v1", opener=recorder)
        result = client.create([{"role": "user", "content": [{"type": "input_text", "text": "x"}]}], [])
        self.assertEqual(result["output"], [])
        request = recorder.requests[0]
        body = json.loads(request.data)
        self.assertEqual(body["model"], "gpt-6-sol")
        self.assertEqual(request.get_header("User-agent"), "script2video-agent-responses/1.0")

    def test_unknown_video_status_is_rejected(self):
        recorder = Recorder([b'{"status":"running"}'])
        with self.assertRaises(AgentError):
            VideoClient("secret", base="https://api.test/v1", opener=recorder).status("job-1")

    def test_responses_loop_dispatches_allowlisted_plan_tool(self):
        class Planner:
            def __init__(self):
                self.calls = 0
            def create(self, items, tools):
                self.calls += 1
                if self.calls == 1:
                    return {"output": [{"type": "function_call", "name": "plan_shots",
                        "arguments": json.dumps({"shots": [{"id": "shot-01", "prompt": "x"}], "reason": "draft"}),
                        "call_id": "call-1"}]}
                return {"output": [{"type": "message", "content": []}]}
        with tempfile.TemporaryDirectory() as directory:
            agent = ScriptAgent(pathlib.Path(directory) / "state.json",
                                VideoClient("secret", base="https://api.test/v1", opener=Recorder([])))
            result = agent.responses_loop(Planner(), "make one shot")
            self.assertEqual(result["output"][0]["type"], "message")
            self.assertEqual(agent.state["shots"]["shot-01"]["status"], "planned")


if __name__ == "__main__":
    unittest.main()
