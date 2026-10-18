from __future__ import annotations

import asyncio
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx2
import pytest

from helpers import run_cli
from systemoneprompts import parse_definition
from systemoneprompts.cache import FetchResponse, create_caching_fetch
from systemoneprompts.client import TypeSafeClient, TypeSafeClientError
from systemoneprompts.diagnostics import SystemOnePromptsError
from systemoneprompts.evaluation import execute_eval
from systemoneprompts.provider import create_client

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
QUESTIONS = {"q": {"type": "noul"}}
RESPONSE = {"model": "jev-test", "answers": {"q": {"type": "noul", "noul": 0.9}}, "usage": {"input_tokens": 1, "output_tokens": 1}}
OPT_IN = "TypeSafe-Danger-Zone-Images"


def image(name="rectangle.png"):
    data = (Path(__file__).parents[1] / "conformance/v1/images" / name).read_bytes()
    return {"type": "image", "format": "jpg" if name.endswith("jpg") else "png", "data_base64": base64.b64encode(data).decode()}


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("assets", [{}, None])
def test_empty_assets_preserve_text_requests_and_cache(tmp_path, cached, assets):
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=RESPONSE)

    definition = parse_definition('[questions.q]\ntype="noul"')
    created = create_client(definition, cache=cached, cache_root=str(tmp_path), env={}, transport=httpx2.MockTransport(handle))
    client = created["client"]
    try:
        assert client.system_one_sync(state={}, questions=QUESTIONS, assets=assets)["answers"] == RESPONSE["answers"]
        client.system_one_sync(state={}, questions=QUESTIONS)
        assert len(seen) == (1 if cached else 2)
        assert all("assets" not in request for request in seen)
        assert not (tmp_path / "images").exists()
    finally:
        client.close()


def test_bare_cache_empty_assets_share_ordinary_text_entries(tmp_path):
    seen = []

    def network(_url, options):
        seen.append(json.loads(options["body"]))
        return FetchResponse(status=200, body=json.dumps(RESPONSE).encode())

    cache = create_caching_fetch(dir=str(tmp_path), fetch=network)
    body = {"state": {}, "questions": QUESTIONS, "model": "jev-test"}
    cache(ENDPOINT, {"method": "POST", "body": json.dumps({**body, "assets": {}})})
    cache(ENDPOINT, {"method": "POST", "body": json.dumps(body)})
    assert len(seen) == 1
    assert "assets" not in seen[0]
    assert not (tmp_path / "images").exists()


@pytest.mark.parametrize("mode", ["read-write", "read-only", "refresh"])
def test_bare_cache_rejects_explicit_null_assets_before_cache_or_network(tmp_path, mode):
    seen = []

    def network(url, options):
        seen.append((url, options))
        return FetchResponse(status=200, body=json.dumps(RESPONSE).encode())

    cache = create_caching_fetch(dir=str(tmp_path), fetch=network, mode=mode)
    body = {"state": {}, "questions": QUESTIONS, "model": "jev-test", "assets": None}
    with pytest.raises(SystemOnePromptsError, match="assets must be an image reference map"):
        cache(ENDPOINT, {"method": "POST", "headers": {OPT_IN: "true"}, "body": json.dumps(body)})
    assert seen == []
    assert list(tmp_path.iterdir()) == []
    assert cache.stats().requests == 0


@pytest.mark.parametrize("async_http", [False, True])
def test_effective_header_override_is_validated_and_sent_once(async_http):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx2.Response(200, json=RESPONSE)

    async def exercise():
        cls = httpx2.AsyncClient if async_http else httpx2.Client
        http = cls(transport=httpx2.MockTransport(handle))
        client = TypeSafeClient(api_key="owned", http_client=http, environ={}, headers={OPT_IN: "true", "X-Trace": "default"})
        kwargs = {"state": "<asset:photo>", "questions": QUESTIONS, "assets": {"<asset:photo>": image()}}
        async def call(headers):
            if async_http:
                return await client.system_one(**kwargs, headers=headers)
            return client.system_one_sync(**kwargs, headers=headers)
        try:
            with pytest.raises(TypeSafeClientError, match="require"):
                await call({OPT_IN.lower(): "false"})
            assert seen == []
            client.default_headers[OPT_IN] = "false"
            await call({OPT_IN.lower(): "true", "x-trace": "call", "authorization": "hijack", "content-type": "text/plain"})
            assert seen[0].headers.get_list(OPT_IN) == ["true"]
            assert seen[0].headers.get_list("x-trace") == ["call"]
            assert seen[0].headers.get_list("authorization") == ["Bearer owned"]
            assert seen[0].headers.get_list("content-type") == ["application/json"]
        finally:
            if async_http:
                await http.aclose()
            else:
                http.close()
    asyncio.run(exercise())


def test_cached_header_false_override_fails_before_provider(tmp_path):
    seen = []
    definition = parse_definition('[questions.q]\ntype="noul"')
    def handle(request):
        seen.append(request)
        return httpx2.Response(200, json=RESPONSE)
    created = create_client(definition, cache=True, cache_root=str(tmp_path), env={}, transport=httpx2.MockTransport(handle))
    client = created["client"]
    client.default_headers[OPT_IN] = "true"
    try:
        with pytest.raises(TypeSafeClientError):
            client.system_one_sync(state="<asset:photo>", questions=QUESTIONS, assets={"<asset:photo>": image()}, headers={OPT_IN.lower(): "false"})
        assert seen == []
        client.system_one_sync(state="<asset:photo>", questions=QUESTIONS, assets={"<asset:photo>": image()}, headers={OPT_IN.lower(): "true"})
        assert seen[0].headers.get_list(OPT_IN) == ["true"]
    finally:
        client.close()


@pytest.mark.parametrize("invalid", [[], [1], False, None, "bad", 1])
def test_execute_eval_rejects_malformed_shared_assets_before_calls(invalid):
    definition = parse_definition('[questions.q]\ntype="noul"')
    class Client:
        calls = []
        async def system_one(self, **kwargs):
            self.calls.append(kwargs)
            return RESPONSE
    client = Client()
    with pytest.raises(SystemOnePromptsError, match="map"):
        asyncio.run(execute_eval(definition, [{"state": {}}], client, model="jev-test", assets=invalid))
    assert client.calls == []


@pytest.mark.parametrize("bad_case", [{"state": {}, "assets": False}, {"state": {}, "labels": {"missing": True}}, {"state": 2}])
def test_execute_eval_validates_all_cases_before_calls(bad_case):
    definition = parse_definition('[questions.q]\ntype="noul"')
    class Client:
        calls = []
        async def system_one(self, **kwargs):
            self.calls.append(kwargs)
            return RESPONSE
    client = Client()
    with pytest.raises(SystemOnePromptsError):
        asyncio.run(execute_eval(definition, [{"state": {}}, bad_case], client, model="jev-test"))
    assert client.calls == []


@pytest.mark.parametrize("invalid", [[], [1], False, None, "bad", 1])
def test_cli_eval_rejects_malformed_shared_assets_cleanly(tmp_path, invalid):
    definition = tmp_path / "definition.toml"
    definition.write_text('[questions.q]\ntype="noul"')
    cases = tmp_path / "cases.jsonl"
    cases.write_text('{"state":{}}\n')
    assets = tmp_path / "assets.json"
    assets.write_text(json.dumps(invalid))
    result = run_cli(["eval", str(definition), "--cases", str(cases), "--assets", str(assets)])
    assert result.returncode == 1
    assert "assets must be an image reference map" in result.stderr
    assert "Traceback" not in result.stderr
    assert "credentials" not in result.stderr


def test_cli_eval_shared_assets_and_case_override_reach_provider(tmp_path):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            body = json.dumps(RESPONSE).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        definition = tmp_path / "definition.toml"
        definition.write_text('[assets.photo]\nruntime=true\n[questions.q]\ntype="noul"\ninstructions="Inspect <asset:photo>"')
        shared = image()
        override = image("rectangle.jpg")
        assets = tmp_path / "assets.json"
        assets.write_text(json.dumps({"photo": shared}))
        cases = tmp_path / "cases.jsonl"
        cases.write_text(json.dumps({"state": {}, "labels": {"q": True}}) + "\n" + json.dumps({"state": {}, "assets": {"photo": override}, "labels": {"q": True}}) + "\n")
        result = run_cli(["eval", str(definition), "--cases", str(cases), "--assets", str(assets), "--experimental-images", "--base-url", f"http://127.0.0.1:{server.server_port}"], env={"TYPESAFE_API_KEY": "test"})
        assert result.returncode == 0, result.stderr
        assert [request["assets"] for request in seen] == [{"<asset:photo>": shared}, {"<asset:photo>": override}]
        assert json.loads(result.stdout)["questions"]["q"]["correct"] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_box_still_requires_opt_in_with_empty_assets():
    client = TypeSafeClient(environ={}, transport=httpx2.MockTransport(lambda request: pytest.fail("network called")))
    try:
        with pytest.raises(TypeSafeClientError, match="require"):
            client.system_one_sync(state={}, questions={"q": {"type": "box"}}, assets={})
        with pytest.raises(SystemOnePromptsError, match="map"):
            client.system_one_sync(state={}, questions=QUESTIONS, assets=[])
    finally:
        client.close()


def test_execute_eval_empty_shared_assets_are_legal():
    definition = parse_definition('[questions.q]\ntype="noul"')
    class Client:
        async def system_one(self, **kwargs):
            assert "assets" not in kwargs
            return RESPONSE
    report = asyncio.run(execute_eval(definition, [{"state": {}}], Client(), model="jev-test", assets={}))
    assert report["errors"] == 0
