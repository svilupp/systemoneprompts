from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx2
import pytest

from systemoneprompts import OpenAIDecisionsClient, OpenAIDecisionsError
from systemoneprompts.cache import CacheMissError, cache_stats, question_hash
from systemoneprompts.cli import main
from systemoneprompts.dev import create_cached_openai_decisions_client, openai_cache_dir

QUESTIONS = {
    "__proto__": {"type": "noul", "instructions": "Is it true?"},
    "c": {"type": "choice", "criteria": {"__proto__": None, "constructor": "Other"}},
    "s": {"type": "score", "criteria": ["Low", {"description": "High"}]},
}
STATE = {"z": 1e-7, "a": ["é", True, None]}


class Network:
    def __init__(self, base_url=None):
        self.calls = []
        self.refuse = False
        self.client = OpenAIDecisionsClient(
            api_key="test",
            base_url=base_url,
            max_retries=0,
            transport=httpx2.MockTransport(self.handle),
        )

    def handle(self, request):
        body = json.loads(request.content)
        self.calls.append(body)
        answers = []
        for q in body["questions"]:
            item = {"name": q["name"], "type": q["type"]}
            if self.refuse:
                item["type"] = "refusal"
            elif q["type"] == "predicate":
                item["probability"] = 0.8
            elif q["type"] == "choice":
                item.update(
                    choice=q["choices"][0]["value"],
                    confidence=0.6,
                    probabilities=[
                        {"value": c["value"], "probability": 0.8 if i == 0 else 0.2}
                        for i, c in enumerate(q["choices"])
                    ],
                )
            else:
                item.update(
                    score=0.2,
                    confidence=0.7,
                    probabilities=[
                        {"value": i, "probability": 0.8 if i == 0 else 0.2}
                        for i in range(len(q["levels"]))
                    ],
                )
            answers.append(item)
        return httpx2.Response(
            200,
            json={
                "model": "reported",
                "answers": answers,
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        )


def record(directory, identifier):
    digest = question_hash(
        {"model": "gpt-6-luna", "id": identifier, "state": STATE, "question": QUESTIONS[identifier]}
    )
    return Path(directory) / digest[:2] / f"{digest}.json"


def test_canonical_cache_partial_and_all_hits(tmp_path):
    network = Network()
    made = create_cached_openai_decisions_client(client=network.client, dir=str(tmp_path))
    client, cache = made["client"], made["cache"]

    async def run():
        first = await client.system_one(
            state=STATE, questions={"__proto__": QUESTIONS["__proto__"]}
        )
        partial = await client.system_one(state=STATE, questions=QUESTIONS)
        hit = await client.system_one(state=STATE, questions=QUESTIONS)
        assert first["answers"]["__proto__"] == partial["answers"]["__proto__"]
        assert hit["answers"] == partial["answers"]
        assert hit["usage"] == {"input_tokens": 0, "output_tokens": 0}
        assert partial["usage"]["input_tokens"] == 10

    try:
        asyncio.run(run())
        assert len(network.calls) == 2
        assert [(q["name"], q["type"]) for q in network.calls[1]["questions"]] == [
            ("q0", "choice"),
            ("q1", "score"),
        ]
        assert (cache.stats().requests, cache.stats().hits, cache.stats().misses) == (3, 4, 3)
        assert cache_stats(cache.dir)["entries"] == 3
    finally:
        client.close()
        network.client.close()


def test_invalid_entries_readonly_refresh_and_refusal(tmp_path):
    network = Network()
    made = create_cached_openai_decisions_client(client=network.client, dir=str(tmp_path))
    readonly = create_cached_openai_decisions_client(
        client=network.client, dir=str(tmp_path), mode="read-only"
    )
    refresh = create_cached_openai_decisions_client(
        client=network.client, dir=str(tmp_path), mode="refresh"
    )
    client, cache = made["client"], made["cache"]

    async def run():
        await client.system_one(state=STATE, questions=QUESTIONS)
        path = record(cache.dir, "s")
        item = json.loads(path.read_text())
        item["answer"]["legend"] = {"0": "wrong", "1": "wrong"}
        path.write_text(json.dumps(item))
        with pytest.raises(CacheMissError):
            await readonly["client"].system_one(state=STATE, questions=QUESTIONS)
        assert len(network.calls) == 1
        await client.system_one(state=STATE, questions=QUESTIONS)
        assert [q["type"] for q in network.calls[-1]["questions"]] == ["score"]
        path = record(cache.dir, "__proto__")
        item = json.loads(path.read_text())
        item["answer"]["noul"] = 2
        path.write_text(json.dumps(item))
        await client.system_one(state=STATE, questions=QUESTIONS)
        assert [q["type"] for q in network.calls[-1]["questions"]] == ["predicate"]
        record(cache.dir, "c").write_text("{malformed")
        await client.system_one(state=STATE, questions=QUESTIONS)
        assert [q["type"] for q in network.calls[-1]["questions"]] == ["choice"]
        await refresh["client"].system_one(state=STATE, questions=QUESTIONS)
        assert len(network.calls[-1]["questions"]) == 3
        network.refuse = True
        with pytest.raises(OpenAIDecisionsError) as error:
            await refresh["client"].system_one(state="uncached", questions=QUESTIONS)
        assert error.value.kind == "refusal"
        assert cache_stats(cache.dir)["entries"] == 3

    try:
        asyncio.run(run())
    finally:
        for item in [made, readonly, refresh]:
            item["client"].close()
        network.client.close()


def test_scope_isolation_and_cli_stats_clear(tmp_path, capsys):
    network = Network()
    made = create_cached_openai_decisions_client(client=network.client, dir=str(tmp_path))
    other = Network("https://other.test/v1/")
    isolated = create_cached_openai_decisions_client(
        client=other.client, dir=str(tmp_path), mode="read-only"
    )
    try:
        asyncio.run(made["client"].system_one(state=STATE, questions=QUESTIONS))
        assert (
            openai_cache_dir(dir=str(tmp_path), base_url="https://api.openai.com/v1/decisions/")
            == made["cache"].dir
        )
        with pytest.raises(CacheMissError):
            asyncio.run(isolated["client"].system_one(state=STATE, questions=QUESTIONS))
        assert not other.calls
        assert main(["cache", "stats", "--provider", "openai", "--cache-root", str(tmp_path)]) == 0
        assert "entries  3" in capsys.readouterr().out
        native = tmp_path / "cache" / "sentinel"
        native.parent.mkdir(parents=True)
        native.write_text("native")
        version = Path(made["cache"].dir.replace("/v1/", "/v2/")) / "sentinel"
        version.parent.mkdir(parents=True)
        version.write_text("v2")
        assert main(["cache", "clear", "--provider", "openai", "--cache-root", str(tmp_path)]) == 0
        assert native.read_text() == "native"
        assert version.read_text() == "v2"
        assert main(["cache", "clear", "--cache-root", str(tmp_path)]) == 0
        assert not native.exists()
        assert version.exists()
    finally:
        made["client"].close()
        isolated["client"].close()
        network.client.close()
        other.client.close()


def test_preflight_on_hits_and_invalid_wire_write_nothing(tmp_path):
    calls = []

    def bad(request):
        calls.append(request)
        return httpx2.Response(200, json={"model": "bad", "answers": []})

    network = OpenAIDecisionsClient(transport=httpx2.MockTransport(bad))
    made = create_cached_openai_decisions_client(client=network, dir=str(tmp_path))

    async def run():
        with pytest.raises(OpenAIDecisionsError) as error:
            await made["client"].system_one(state=STATE, questions=QUESTIONS)
        assert error.value.kind == "response"
        for kwargs in [
            {"state": STATE, "questions": QUESTIONS, "model": " "},
            {"state": float("nan"), "questions": QUESTIONS},
        ]:
            with pytest.raises(OpenAIDecisionsError):
                await made["client"].system_one(**kwargs)
        assert len(calls) == 1
        assert cache_stats(made["cache"].dir)["entries"] == 0

    try:
        asyncio.run(run())
    finally:
        made["client"].close()
        network.close()


def test_shared_strict_validators_cover_records_and_final_merges():
    from systemoneprompts.openai_decisions import (
        _is_valid_decisions_answer,
        _validate_normalized_result,
    )
    rows = json.loads((Path(__file__).resolve().parents[1] / "conformance/v1/providers/openai-cache-validation.json").read_text())
    for row in rows:
        assert _is_valid_decisions_answer(row["question"], row["answer"]) == row["valid"]
        result = {"model": "cached", "usage": {"input_tokens": 0, "output_tokens": 0}, "answers": {"q": row["answer"]}}
        if row["valid"]:
            assert _validate_normalized_result(result, {"q": row["question"]})["answers"]["q"] == row["answer"]
        else:
            with pytest.raises(OpenAIDecisionsError):
                _validate_normalized_result(result, {"q": row["question"]})


def test_cached_async_transport_uses_caller_loop_and_propagates_cancellation(tmp_path):
    async def run():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        stopped = asyncio.Event()
        class Transport:
            closed = False
            async def request(self, *args, **kwargs):
                assert asyncio.get_running_loop() is loop
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    stopped.set()
                    raise
            def close(self):
                self.closed = True
        transport = Transport()
        network = OpenAIDecisionsClient(api_key="test", http_client=transport, max_retries=0)
        made = create_cached_openai_decisions_client(client=network, dir=str(tmp_path))
        try:
            task = asyncio.create_task(made["client"].system_one(state=STATE, questions=QUESTIONS))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(stopped.wait(), 2)
            assert cache_stats(made["cache"].dir)["entries"] == 0
        finally:
            made["client"].close()
            network.close()
        assert not transport.closed
    asyncio.run(run())


@pytest.mark.parametrize("base_url", ["https://user:secret@example.test/v1", "file:///tmp/v1", "https://example.test/v1?key=secret", "https://example.test/v1#fragment", ""])
def test_cache_origin_rejects_credentials_and_non_endpoint_components(base_url):
    with pytest.raises(OpenAIDecisionsError):
        openai_cache_dir(base_url=base_url)


def test_cache_origin_normalizes_decisions_suffix():
    assert openai_cache_dir(base_url="https://example.test/v1/decisions/") == openai_cache_dir(base_url="https://example.test/v1")
