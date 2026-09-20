from __future__ import annotations

import asyncio
import math

import pytest

from systemoneprompts.patterns import positive_integer, run_many, walk_taxonomy
from systemoneprompts.provider import FakeClient


def test_run_many_rejects_invalid_concurrency_before_calling_the_client() -> None:
    client = FakeClient(lambda _request: {"model": "test", "answers": {}, "usage": {}})
    for concurrency in (-1, 0):
        with pytest.raises(ValueError, match="concurrency must be a positive integer"):
            asyncio.run(
                run_many(client, questions={}, states=[{}], concurrency=concurrency)
            )
    with pytest.raises(ValueError, match="concurrency must be a positive integer"):
        asyncio.run(run_many(client, questions={}, states=[{}], concurrency=1.5))  # type: ignore[arg-type]
    assert client.calls == []


def test_run_many_preserves_order_and_collects_errors() -> None:
    async def handler(request: dict[str, object]) -> dict[str, object]:
        n = request["state"]["n"]  # type: ignore[index]
        if n == 2:
            raise RuntimeError("boom")
        return {
            "model": "jev-latest",
            "answers": {"ok": {"type": "noul", "noul": n}},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }

    client = FakeClient(handler)
    seen: list[int] = []

    async def main() -> list[object]:
        return await run_many(
            client,
            questions={"ok": {"type": "noul", "instructions": "ok?"}},
            states=[{"n": 1}, {"n": 2}, {"n": 3}],
            concurrency=2,
            on_result=lambda index, _result: seen.append(index),
        )

    results = asyncio.run(main())
    assert len(results) == 3
    assert sorted(seen) == [0, 1, 2]
    assert results[0]["answers"]["ok"]["noul"] == 1  # type: ignore[index]
    assert isinstance(results[1], RuntimeError)
    assert results[2]["answers"]["ok"]["noul"] == 3  # type: ignore[index]


def test_run_many_callback_failure_rejects_without_retries() -> None:
    client = FakeClient(lambda _request: {"model": "test", "answers": {}, "usage": {}})
    callbacks = 0

    def on_result(_index: int, _result: object) -> None:
        nonlocal callbacks
        callbacks += 1
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        asyncio.run(run_many(client, questions={}, states=[{}], on_result=on_result))
    assert callbacks == 1
    assert len(client.calls) == 1


def test_run_many_empty_batch() -> None:
    client = FakeClient(lambda _request: (_ for _ in ()).throw(RuntimeError("should not be called")))
    assert asyncio.run(run_many(client, questions={}, states=[])) == []
    with pytest.raises(ValueError, match="concurrency must be a positive integer"):
        asyncio.run(run_many(client, questions={}, states=[], concurrency=0))


def test_run_many_items_use_their_questions_and_preserve_order() -> None:
    async def handler(request: dict[str, object]) -> dict[str, object]:
        n = request["state"]["id"]  # type: ignore[index]
        return {
            "model": "test",
            "answers": {"id": {"type": "noul", "noul": n}},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }

    client = FakeClient(handler)
    results = asyncio.run(
        run_many(
            client,
            items=[
                {"state": {"id": 1}, "questions": {"a": {"type": "noul", "instructions": "a?"}}},
                {"state": {"id": 2}, "questions": {"b": {"type": "noul", "instructions": "b?"}}},
            ],
            concurrency=2,
        )
    )
    assert len(results) == 2
    assert results[0]["answers"]["id"]["noul"] == 1  # type: ignore[index]
    assert results[1]["answers"]["id"]["noul"] == 2  # type: ignore[index]
    by_id = {call["state"]["id"]: call["questions"] for call in client.calls}
    assert by_id == {
        1: {"a": {"type": "noul", "instructions": "a?"}},
        2: {"b": {"type": "noul", "instructions": "b?"}},
    }


def test_run_many_items_inherit_shared_model_unless_overridden() -> None:
    client = FakeClient(
        lambda request: {"model": request.get("model"), "answers": {}, "usage": {}}
    )
    question = {"q": {"type": "noul"}}
    asyncio.run(
        run_many(
            client,
            items=[
                {"state": {"id": 1}, "questions": question},
                {"state": {"id": 2}, "questions": question, "model": None},
                {"state": {"id": 3}, "questions": question, "model": "own"},
            ],
            model="shared",
        )
    )
    by_id = {call["state"]["id"]: call.get("model") for call in client.calls}
    assert by_id == {1: "shared", 2: "shared", 3: "own"}


def test_run_many_rejects_mixing_items_and_states_before_calling() -> None:
    client = FakeClient(lambda _request: {"model": "test", "answers": {}, "usage": {}})
    with pytest.raises(ValueError, match="run_many accepts either items or states, not both"):
        asyncio.run(
            run_many(
                client,
                questions={},
                states=[{}],
                items=[{"state": {}, "questions": {}}],
            )
        )
    assert client.calls == []
    with pytest.raises(ValueError, match="run_many accepts either items or states, not both"):
        asyncio.run(run_many(client, questions={}, items=[{"state": {}, "questions": {}}]))
    assert client.calls == []


def test_run_many_empty_items() -> None:
    client = FakeClient(lambda _request: (_ for _ in ()).throw(RuntimeError("should not be called")))
    assert asyncio.run(run_many(client, items=[])) == []
    assert client.calls == []


def test_run_many_keeps_none_results_and_accepts_sync_clients() -> None:
    class SyncClient:
        def system_one(self, *, state, questions, model=None):  # type: ignore[no-untyped-def]
            return None if state == "none" else {"model": "sync", "answers": {}, "usage": {}}

    results = asyncio.run(
        run_many(SyncClient(), questions={}, states=["none", "ok"], concurrency=None)  # type: ignore[arg-type]
    )
    assert results[0] is None
    assert results[1]["model"] == "sync"  # type: ignore[index]


def test_run_many_lets_base_exceptions_propagate() -> None:
    client = FakeClient(lambda _request: KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(run_many(client, questions={}, states=[{}]))


def test_walk_taxonomy_rejects_broken_responses_and_tolerates_odd_probabilities() -> None:
    broken = FakeClient(lambda _request: {"model": "t", "answers": {}, "usage": {}})
    with pytest.raises(TypeError, match="probabilities"):
        asyncio.run(walk_taxonomy(broken, state={}, tree={"A": "a", "B": "b"}))
    odd = FakeClient(
        lambda _request: {
            "model": "t",
            "answers": {"step": {"type": "choice", "probabilities": {"A": "abc", "B": 0.5}}},
            "usage": {},
        }
    )
    result = asyncio.run(walk_taxonomy(odd, state={}, tree={"A": "a", "B": "b"}, beam_width=None))
    assert result == [{"path": ["B"], "probability": 0.5}]
    huge = FakeClient(
        lambda _request: {
            "model": "t",
            "answers": {"step": {"type": "choice", "probabilities": {"A": 10**1000, "B": 0.5}}},
            "usage": {},
        }
    )
    result = asyncio.run(walk_taxonomy(huge, state={}, tree={"A": "a", "B": "b"}, beam_width=1))
    assert result == [{"path": ["A"], "probability": math.inf}]


def test_walk_taxonomy_rejects_invalid_beam_width() -> None:
    client = FakeClient(lambda _request: (_ for _ in ()).throw(RuntimeError("unexpected")))
    with pytest.raises(ValueError, match="beamWidth must be a positive integer"):
        asyncio.run(walk_taxonomy(client, state={}, tree={"A": "a"}, beam_width=0))
    assert client.calls == []


def _prefer_first(request: dict[str, object]) -> dict[str, object]:
    questions = request["questions"]
    step = questions["step"]  # type: ignore[index]
    labels = list(step["criteria"])  # type: ignore[index]
    probabilities = {
        label: 0.7 if index == 0 else 0.3 / max(1, len(labels) - 1)
        for index, label in enumerate(labels)
    }
    return {
        "model": "jev-latest",
        "answers": {
            "step": {
                "type": "choice",
                "choice": labels[0],
                "confidence": 0.7,
                "probabilities": probabilities,
            }
        },
        "usage": {"input_tokens": 1, "output_tokens": 0},
    }


def test_walk_taxonomy_keeps_a_beam() -> None:
    client = FakeClient(_prefer_first)
    paths = asyncio.run(
        walk_taxonomy(
            client,
            state={"title": "bike bottle"},
            instructions="Which department?",
            beam_width=2,
            tree={
                "Sporting": {"Cycling": {"Bottles": "Bike bottles"}},
                "Home": {"Drinkware": {"Bottles": "Kitchen bottles"}},
            },
        )
    )
    assert len(paths) == 2
    assert paths[0]["path"] == ["Sporting", "Cycling", "Bottles"]
    assert paths[0]["probability"] == pytest.approx(0.7**3)
    assert paths[1]["path"] == ["Home", "Drinkware", "Bottles"]
    assert paths[1]["probability"] == pytest.approx(0.3 * 0.7 * 0.7)


def test_walk_taxonomy_explicit_nodes() -> None:
    seen: list[object] = []

    def handler(request: dict[str, object]) -> dict[str, object]:
        questions = request["questions"]
        seen.append(questions["step"]["criteria"])  # type: ignore[index]
        return _prefer_first(request)

    client = FakeClient(handler)
    paths = asyncio.run(
        walk_taxonomy(
            client,
            state={},
            tree={
                "A": {"description": "leaf a"},
                "B": {"description": "branch b", "children": {"B1": "leaf b1"}},
            },
        )
    )
    assert seen[0] == {"A": "leaf a", "B": {"B1": "leaf b1"}}
    assert paths == [{"path": ["A"], "probability": 0.7}]


def test_positive_integer_rejects_bools() -> None:
    with pytest.raises(ValueError):
        positive_integer("concurrency", True, 4)
