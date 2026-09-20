"""Provider-neutral orchestration helpers."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

_UNSET: Any = object()


class SystemOneClient(Protocol):
    """The slice of a TypeSafe client that patterns and tests need."""

    async def system_one(
        self,
        *,
        state: Any,
        questions: Mapping[str, Any],
        model: str | None = None,
    ) -> Mapping[str, Any]: ...


def positive_integer(name: str, value: Any, default: int) -> int:
    """Validate an optional positive integer option; `None` selects `default`."""
    if value is None:
        return default
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


async def _call(client: Any, **request: Any) -> Any:
    """Await `system_one` whether it is a coroutine function or a plain method."""
    result = client.system_one(**request)
    if inspect.isawaitable(result):
        result = await result
    return result


async def run_many(
    client: SystemOneClient,
    *,
    questions: Mapping[str, Any] | None = None,
    states: Sequence[Any] | None = None,
    items: Sequence[Any] | None = None,
    model: str | None = None,
    concurrency: int | None = 4,
    on_result: Callable[[int, Any], None] | None = None,
) -> list[Any]:
    """Ask questions about many states with bounded concurrency.

    Pass shared `questions` + `states`, or per-item `{state, questions}` mappings.
    Results keep input order (whatever the client returned, including `None`). A
    state whose call raises an `Exception` yields that exception instead of aborting
    the batch; `BaseException`s such as `KeyboardInterrupt` propagate. `on_result` is
    called once as each result settles; a throwing callback rejects the batch without
    retries. `concurrency=None` selects the default of 4.
    """
    workers_limit = positive_integer("concurrency", concurrency, 4)
    jobs = _run_many_jobs(questions=questions, states=states, items=items, model=model)
    if not jobs:
        return []
    workers = min(workers_limit, len(jobs))
    results: list[Any] = [_UNSET] * len(jobs)
    next_index = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal next_index
        while True:
            async with lock:
                index = next_index
                next_index += 1
            if index >= len(jobs):
                return
            job = jobs[index]
            try:
                result = await _call(
                    client, state=job["state"], questions=job["questions"], model=job["model"]
                )
            except Exception as error:
                result = error
            results[index] = result
            if on_result is not None:
                on_result(index, result)

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(workers)])
    return [RuntimeError("missing result") if item is _UNSET else item for item in results]


def _run_many_jobs(
    *,
    questions: Mapping[str, Any] | None,
    states: Sequence[Any] | None,
    items: Sequence[Any] | None,
    model: str | None,
) -> list[dict[str, Any]]:
    if items is not None:
        if states is not None or questions is not None:
            raise ValueError("run_many accepts either items or states, not both")
        jobs: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping):
                raise TypeError("run_many item must be a mapping with state and questions")
            if "state" not in item or "questions" not in item:
                raise ValueError("run_many item requires state and questions")
            jobs.append(
                {
                    "state": item["state"],
                    "questions": item["questions"],
                    "model": model if item.get("model") is None else item["model"],
                }
            )
        return jobs
    if questions is None or states is None:
        raise TypeError("run_many() missing required keyword-only arguments: 'questions' and 'states'")
    return [{"state": state, "questions": questions, "model": model} for state in states]


class TaxonomyNode(dict[str, Any]):
    """Explicit node: optional `description` plus optional `children`."""


TaxonomyTree = dict[str, Any]


async def walk_taxonomy(
    client: SystemOneClient,
    *,
    state: Any,
    tree: Mapping[str, Any],
    instructions: Any = None,
    beam_width: int | None = 1,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Approximate hierarchical Choice search. Beam pruning can discard a better leaf.

    Each level asks one Choice question (id `step`) sequentially. A response without a
    `step` answer carrying a `probabilities` mapping is a client error and raises
    `TypeError`; labels missing from the mapping (or with non-numeric values) score 0.
    """
    width = positive_integer("beamWidth", beam_width, 1)
    beam: list[dict[str, Any]] = [{"path": [], "probability": 1.0, "node": dict(tree)}]
    finished: list[dict[str, Any]] = []

    while beam:
        expanded: list[dict[str, Any]] = []
        for item in beam:
            node = item["node"]
            labels = list(node)
            if not labels:
                finished.append({"path": item["path"], "probability": item["probability"]})
                continue
            criteria = {label: _subtree_description(node[label]) for label in labels}
            questions: dict[str, Any] = {
                "step": {
                    "type": "choice",
                    **({"instructions": instructions} if instructions is not None else {}),
                    "criteria": criteria,
                }
            }
            response = await _call(client, state=state, questions=questions, model=model)
            probabilities = _step_probabilities(response)
            for label in labels:
                probability = item["probability"] * _probability(probabilities.get(label))
                expanded.append(
                    {
                        "path": [*item["path"], label],
                        "probability": probability,
                        "node": _children_of(node[label]),
                    }
                )
        expanded.sort(key=lambda row: row["probability"], reverse=True)
        continuing: list[dict[str, Any]] = []
        for item in expanded:
            if not item["node"]:
                finished.append({"path": item["path"], "probability": item["probability"]})
            else:
                continuing.append(item)
        beam = continuing[:width]

    finished.sort(key=lambda row: row["probability"], reverse=True)
    return finished[:width]


def _step_probabilities(response: Any) -> Mapping[str, Any]:
    answers = response.get("answers") if isinstance(response, Mapping) else None
    step = answers.get("step") if isinstance(answers, Mapping) else None
    probabilities = step.get("probabilities") if isinstance(step, Mapping) else None
    if not isinstance(probabilities, Mapping):
        raise TypeError("walk_taxonomy: response lacks a Choice `step` answer with probabilities")
    return probabilities


def _probability(value: Any) -> float:
    if type(value) is int or type(value) is float:
        try:
            return float(value)
        except OverflowError:
            return math.inf if value > 0 else -math.inf
    return 0.0


def _children_of(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {}
    if _is_node(value):
        children = value.get("children")
        return dict(children) if isinstance(children, Mapping) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _subtree_description(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if _is_node(value):
        children = value.get("children")
        if isinstance(children, Mapping) and children:
            return _tree_description(children)
        return value.get("description")
    if isinstance(value, Mapping):
        return _tree_description(value)
    return None


def _tree_description(tree: Mapping[str, Any]) -> dict[str, Any]:
    return {label: _subtree_description(child) for label, child in tree.items()}


def _is_node(value: Any) -> bool:
    return isinstance(value, Mapping) and ("description" in value or "children" in value)


__all__ = [
    "SystemOneClient",
    "TaxonomyNode",
    "TaxonomyTree",
    "positive_integer",
    "run_many",
    "walk_taxonomy",
]
