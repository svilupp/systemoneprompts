from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from helpers import fixture, fixture_path
from systemoneprompts import parse_definition
from systemoneprompts.diagnostics import SystemOnePromptsError
from systemoneprompts.evaluation import (
    EvalCaseError,
    execute_eval,
    js_round,
    label_of,
    load_eval_cases,
    preflight_eval,
    prepare_sweep,
    protect_report_path,
    validate_case,
)
from systemoneprompts.provider import FakeClient


def triage():
    return parse_definition(fixture("golden/triage.toml"), filename="triage.toml")


def valid_state() -> dict[str, object]:
    return {
        "ticket": {"message": "ok", "sender": {"email": "a@b.c", "display_name": "A"}},
        "customer": {"open_orders": []},
        "policy": {"sensitive_credentials": []},
    }


def test_eval_labels_match_javascript_string() -> None:
    assert label_of({"type": "noul", "noul": 0.9}) == "true"
    assert label_of({"type": "noul", "noul": 0.1}) == "false"
    assert js_round(1.5) == 2
    assert js_round(2.5) == 3
    assert js_round(-1.5) == -1
    assert js_round(0.499) == 0


def test_load_eval_cases_rejects_malformed_rows() -> None:
    definition = triage()
    text = json.dumps(
        {
            "id": 42,
            "state": 3,
            "labels": {"missing": True},
            "factors": {"topic.billing": "yes"},
        }
    )
    with pytest.raises(EvalCaseError) as caught:
        load_eval_cases(text, "cases.jsonl", definition)
    joined = "\n".join(caught.value.messages)
    assert "unknown question id" in joined
    assert "expected a boolean" in joined
    assert "invalid eval case error(s)" in str(caught.value)


def test_score_integer_valued_float_labels_are_accepted() -> None:
    definition = parse_definition(
        '[questions.mood]\ntype = "score"\ncriteria = ["Calm", "Civil", "Angry"]\n'
    )
    assert validate_case({"state": None, "labels": {"mood": 1.0}}, definition) == []
    errors = validate_case({"state": None, "labels": {"mood": 3}}, definition)
    assert errors and "expected a Score integer" in errors[0]


def test_execute_eval_compares_noul_and_score_labels_like_javascript() -> None:
    definition = parse_definition(
        '[questions.urgent]\ntype = "noul"\n\n[questions.mood]\ntype = "score"\ncriteria = ["Calm", "Civil", "Angry"]\n'
    )

    def handler(_request: dict[str, object]) -> dict[str, object]:
        return {
            "model": "jev-test",
            "answers": {
                "urgent": {"type": "noul", "noul": 0.9},
                "mood": {
                    "type": "score",
                    "score": 1.0,
                    "confidence": 0.8,
                    "legend": {"0": "Calm", "1": "Civil", "2": "Angry"},
                    "probabilities": {"0": 0.1, "1": 0.8, "2": 0.1},
                },
            },
            "usage": {},
        }

    report = asyncio.run(
        execute_eval(
            definition,
            [{"id": "one", "state": None, "labels": {"urgent": True, "mood": 1.0}}],
            FakeClient(handler),
            model="jev-test",
        )
    )
    assert report["errors"] == 0
    assert report["questions"]["urgent"]["confusion"] == {"true": {"true": 1}}
    assert report["questions"]["urgent"]["correct"] == 1
    assert report["questions"]["mood"]["confusion"] == {"1": {"1": 1}}
    assert report["questions"]["mood"]["correct"] == 1


def test_preflight_rejects_invalid_state_before_client_use() -> None:
    definition = triage()
    cases = [{"state": {"ticket": {"message": 42}}}]
    client = FakeClient(lambda _request: (_ for _ in ()).throw(RuntimeError("called")))
    with pytest.raises(EvalCaseError):
        preflight_eval(definition, cases)
    with pytest.raises(EvalCaseError):
        asyncio.run(execute_eval(definition, cases, client, model="test"))
    assert client.calls == []


def test_prepare_sweep_and_missing_truth_samples() -> None:
    definition = triage()
    with pytest.raises(SystemOnePromptsError, match="unknown factor"):
        prepare_sweep("missing", definition)
    sweep = prepare_sweep("customer.high_frustration", definition)
    assert sweep["field"] == "score"
    cases = [{"state": valid_state()}]
    with pytest.raises(SystemOnePromptsError, match="no usable truth samples"):
        preflight_eval(definition, cases, sweep)


def test_protect_report_path(tmp_path: Path) -> None:
    cases = tmp_path / "cases.jsonl"
    cases.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SystemOnePromptsError, match="must not overwrite"):
        protect_report_path(str(cases), str(fixture_path("golden/triage.toml")), str(cases))


def test_execute_eval_partial_metrics_and_factor_failure() -> None:
    definition = triage()
    state = valid_state()

    def handler(request: dict[str, object]) -> dict[str, object]:
        message = request["state"]["ticket"]["message"]  # type: ignore[index]
        if message == "fail":
            raise RuntimeError("mock failure")
        answers = {}
        for qid, question in request["questions"].items():  # type: ignore[union-attr]
            if question["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": 0.9}
            elif question["type"] == "choice":
                answers[qid] = {
                    "type": "choice",
                    "choice": "billing",
                    "confidence": 0.8,
                    "probabilities": {"billing": 0.8, "orders": 0.1, "account": 0.1},
                }
            elif message == "factor-fail":
                answers[qid] = {"type": "score", "confidence": 0.7, "legend": {}, "probabilities": {}}
            else:
                answers[qid] = {
                    "type": "score",
                    "score": 1.7,
                    "confidence": 0.7,
                    "legend": {"0": "Calm", "1": "Civil", "2": "Angry"},
                    "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
                }
        return {"model": "jev-test", "answers": answers, "usage": {"input_tokens": 1, "output_tokens": 1}}

    client = FakeClient(handler)
    cases = [
        {"id": "ok", "state": state, "labels": {"topic": "billing"}},
        {
            "id": "bad-api",
            "state": {**state, "ticket": {**state["ticket"], "message": "fail"}},  # type: ignore[dict-item]
            "labels": {"topic": "billing"},
        },
    ]
    report = asyncio.run(execute_eval(definition, cases, client, model="jev-test"))
    assert report["cases"] == 2
    assert report["errors"] == 1
    assert report["questions"]["topic"] == {
        "accuracy": 1,
        "correct": 1,
        "total": 1,
        "confusion": {"billing": {"billing": 1}},
    }

    fail_client = FakeClient(handler)
    fail_cases = [
        {
            "id": "factor-fail",
            "state": {**state, "ticket": {**state["ticket"], "message": "factor-fail"}},  # type: ignore[dict-item]
            "labels": {"topic": "billing"},
        }
    ]
    failed = asyncio.run(execute_eval(definition, fail_cases, fail_client, model="jev-test"))
    assert failed["errors"] == 1
    assert failed["_stderr"][0].startswith("case factor-fail: factor evaluation failed")
    assert failed["questions"]["topic"]["correct"] == 1


def test_sweep_uses_first_numeric_field() -> None:
    definition = triage()
    state = valid_state()

    def handler(request: dict[str, object]) -> dict[str, object]:
        answers = {}
        for qid, question in request["questions"].items():  # type: ignore[union-attr]
            if question["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": 0.9}
            elif question["type"] == "choice":
                answers[qid] = {
                    "type": "choice",
                    "choice": "billing",
                    "confidence": 0.8,
                    "probabilities": {"billing": 0.8, "orders": 0.1, "account": 0.1},
                }
            else:
                answers[qid] = {
                    "type": "score",
                    "score": 1.7,
                    "confidence": 0.6,
                    "legend": {"0": "Calm", "1": "Civil", "2": "Angry"},
                    "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
                }
        return {"model": "jev-test", "answers": answers, "usage": {}}

    client = FakeClient(handler)
    sweep = prepare_sweep("customer.high_frustration", definition)
    cases = [{"state": {**state, "ticket": {**state["ticket"], "message": "sweep"}}, "factors": {"customer.high_frustration": False}}]  # type: ignore[dict-item]
    report = asyncio.run(execute_eval(definition, cases, client, model="jev-test", sweep=sweep))
    assert report["sweep"]["field"] == "score"
    assert report["sweep"]["rows"][0]["accuracy"] == 1
    assert report["errors"] == 0
