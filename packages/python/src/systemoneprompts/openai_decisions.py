"""OpenAI Decisions REST adapter for the existing System One contract."""

from __future__ import annotations

import asyncio
import copy
import inspect
import math
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx2

from .client import _is_retryable_connection, _retry_after_seconds
from .diagnostics import SystemOnePromptsError, diagnostic
from .json_values import canonical_json, is_json_value
from .locate import index_source
from .questions import validate_questions


class OpenAIDecisionsError(SystemOnePromptsError):
    def __init__(
        self,
        message: str,
        *,
        kind: str,
        body: Any = None,
        status: int | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
        refused_ids: list[str] | None = None,
        code: str | None = None,
    ):
        super().__init__(diagnostic("error", code or f"openai-{kind}", message))
        self.kind = kind
        self.body = body
        self.status = status
        self.request_id = request_id
        self.retry_after = retry_after
        self.refused_ids = refused_ids
        self.code = code


def _incompatible(code: str, message: str) -> Any:
    raise OpenAIDecisionsError(message, kind="compatibility", code=code)


def _model(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        _incompatible("openai-model-empty", "model must be a nonblank string")
    return str(value)


def _empty(value: Any) -> bool:
    return (
        value is None
        or isinstance(value, str)
        and not value.strip()
        or type(value) in (list, dict)
        and not value
    )


def _render(value: Any) -> str:
    return value if isinstance(value, str) else canonical_json(value)


def _encode(state: Any, questions: Any, model: str) -> tuple[dict[str, Any], list[str]]:
    if not is_json_value(state):
        _incompatible("openai-state-json", "state must be JSON-compatible")
    _, diagnostics = validate_questions(questions, index_source(""))
    errors = [d for d in diagnostics if d.severity == "error"]
    if errors:
        _incompatible(errors[0].code, "; ".join(d.message for d in errors))
    ids = list(questions)
    wire = []
    for i, identifier in enumerate(ids):
        question = questions[identifier]
        instructions = question.get("instructions")
        instructions = (
            "Evaluate the supplied evidence against the criteria."
            if _empty(instructions)
            else _render(instructions)
        )
        item: dict[str, Any] = {"name": f"q{i}", "instructions": instructions}
        criteria = question.get("criteria")
        if question["type"] == "noul":
            if _empty(question.get("instructions")) and all(
                _empty(v) for v in (criteria or {}).values()
            ):
                _incompatible(
                    "openai-question-empty",
                    f"question {identifier} needs instructions or outcome criteria",
                )
            item["type"] = "predicate"
            if criteria:
                item["instructions"] += "\nOutcome criteria (JSON): " + canonical_json(criteria)
        elif question["type"] == "choice":
            if len(criteria) < 2:
                _incompatible(
                    "openai-choice-min-options", f"question {identifier} needs at least two options"
                )
            item["type"] = "choice"
            item["choices"] = [
                {"value": k, **({} if v is None else {"description": _render(v)})}
                for k, v in criteria.items()
            ]
        else:
            item["type"] = "score"
            item["levels"] = [
                {"label": str(i), **({} if v is None else {"description": _render(v)})}
                for i, v in enumerate(criteria)
            ]
        wire.append(item)
    return {"model": _model(model), "input": _render(state), "questions": wire}, ids


def _decode(raw: Any, questions: Any, ids: list[str], request_id: str | None) -> dict[str, Any]:
    def invalid(message: str) -> Any:
        raise OpenAIDecisionsError(
            "Invalid Decisions response: " + message,
            kind="response",
            body=raw,
            request_id=request_id,
        )

    def probability(value: Any) -> Any:
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            invalid("invalid probability/confidence")
        return value

    if (
        type(raw) is not dict
        or not isinstance(raw.get("model"), str)
        or type(raw.get("answers")) is not list
        or type(raw.get("usage")) is not dict
    ):
        invalid("model, answers, and usage are required")
    usage = raw["usage"]
    for key in ("input_tokens", "output_tokens"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            invalid("invalid " + key)
    names = {f"q{i}": identifier for i, identifier in enumerate(ids)}
    seen: set[str] = set()
    refused = []
    answers = {}
    for answer in raw["answers"]:
        if (
            type(answer) is not dict
            or not isinstance(answer.get("name"), str)
            or answer["name"] not in names
            or answer["name"] in seen
        ):
            invalid("unexpected or duplicate answer name")
        seen.add(answer["name"])
        identifier = names[answer["name"]]
        question = questions[identifier]
        kind = question["type"]
        if answer.get("type") == "refusal":
            refused.append(identifier)
            continue
        if answer.get("type") != ("predicate" if kind == "noul" else kind):
            invalid("wrong type for " + identifier)
        if kind == "noul":
            answers[identifier] = {"type": "noul", "noul": probability(answer.get("probability"))}
            continue
        labels = (
            list(question["criteria"])
            if kind == "choice"
            else [str(i) for i in range(len(question["criteria"]))]
        )
        if type(answer.get("probabilities")) is not list:
            invalid("missing distribution")
        probabilities = {}
        for item in answer["probabilities"]:
            if type(item) is not dict:
                invalid("invalid distribution entry")
            value = item.get("value")
            if (
                kind == "choice"
                and not isinstance(value, str)
                or kind == "score"
                and type(value) is not int
            ):
                invalid("invalid distribution label/level")
            label = str(value)
            if label not in labels or label in probabilities:
                invalid("unexpected or duplicate distribution entry")
            probabilities[label] = probability(item.get("probability"))
        if len(probabilities) != len(labels):
            invalid("incomplete distribution")
        confidence = probability(answer.get("confidence"))
        if kind == "choice":
            if not isinstance(answer.get("choice"), str) or answer["choice"] not in labels:
                invalid("invalid choice")
            answers[identifier] = {
                "type": kind,
                "choice": answer["choice"],
                "confidence": confidence,
                "probabilities": probabilities,
            }
        else:
            score = answer.get("score")
            if (
                type(score) not in (int, float)
                or not math.isfinite(score)
                or not 0 <= score <= len(labels) - 1
            ):
                invalid("invalid score")
            answers[identifier] = {
                "type": kind,
                "score": score,
                "confidence": confidence,
                "probabilities": probabilities,
                "legend": dict(zip(labels, question["criteria"], strict=True)),
            }
    if len(seen) != len(ids):
        invalid("missing answers")
    if refused:
        raise OpenAIDecisionsError(
            "Decisions refused questions: " + ", ".join(refused),
            kind="refusal",
            body=raw,
            refused_ids=refused,
            request_id=request_id,
        )
    return {
        "model": raw["model"],
        "answers": answers,
        "usage": {k: usage[k] for k in ("input_tokens", "output_tokens")},
    }


class OpenAIDecisionsClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: Any = None,
        http_client: Any = None,
        transport: Any = None,
        headers: Mapping[str, str] | None = None,
        max_retries: int = 2,
        environ: Mapping[str, str | None] | None = None,
    ):
        source = os.environ if environ is None else environ
        self.default_model = _model("gpt-6-luna" if model is None else model)
        self.api_key = (api_key or source.get("OPENAI_API_KEY") or "").strip()
        if not self.api_key and http_client is None and transport is None:
            _incompatible(
                "missing-credentials",
                "OPENAI_API_KEY is not set. Pass api_key or export OPENAI_API_KEY.",
            )
        self.base_url = _normalize_base_url(base_url if base_url is not None else source.get("OPENAI_BASE_URL") or "https://api.openai.com/v1")
        self.timeout = 10.0 if timeout is None else timeout
        if isinstance(self.timeout, (int, float)) and (
            type(self.timeout) is bool or not math.isfinite(self.timeout) or self.timeout <= 0
        ):
            _incompatible("openai-options", "timeout must be positive")
        if type(max_retries) is not int or max_retries < 0:
            _incompatible("openai-options", "max_retries must be a nonnegative integer")
        self.max_retries = max_retries
        if getattr(transport, "systemoneprompts_cache", False):
            _incompatible(
                "openai-cache-transport",
                "Use create_cached_openai_decisions_client instead of a caching transport as raw network I/O",
            )
        if transport is not None and http_client is not None:
            _incompatible("openai-options", "transport cannot be combined with http_client")
        if transport is not None:
            # The HTTP client owns this proxy, while the supplied transport stays caller-owned.
            inner = transport

            class BorrowedTransport(httpx2.BaseTransport):
                def handle_request(self, request: Any) -> Any:
                    return inner.handle_request(request)

                def close(self) -> None:
                    pass

            transport = BorrowedTransport()
        self.default_headers = dict(headers or {})
        self._owns_client = http_client is None
        self._http: Any = (
            http_client
            if http_client is not None
            else httpx2.Client(timeout=self.timeout, transport=transport)
        )
        self._async = inspect.iscoroutinefunction(self._http.request)

    def close(self) -> None:
        if self._owns_client:
            closer = getattr(self._http, "close", None)
            if callable(closer):
                closer()

    async def system_one(
        self,
        *,
        state: Any,
        questions: Mapping[str, Any],
        model: str | None = None,
        timeout: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        snapshot = copy.deepcopy(questions)
        payload, ids = _encode(state, snapshot, self.default_model if model is None else model)
        merged = {
            k: v
            for k, v in {**self.default_headers, **dict(headers or {})}.items()
            if k.lower() not in ("authorization", "content-type", "accept")
        }
        merged.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        actual_timeout = self.timeout if timeout is None else timeout
        if isinstance(actual_timeout, (int, float)) and (
            type(actual_timeout) is bool or not math.isfinite(actual_timeout) or actual_timeout <= 0
        ):
            _incompatible("openai-options", "timeout must be positive")
        for attempt in range(self.max_retries + 1):
            retry_after = None
            try:
                kwargs: dict[str, Any] = {
                    "content": canonical_json(payload).encode("utf-8"),
                    "headers": merged,
                    "timeout": actual_timeout,
                }
                if self._async:
                    response = await self._http.request(
                        "POST", self.base_url + "/decisions", **kwargs
                    )
                else:
                    response = await asyncio.to_thread(
                        self._http.request, "POST", self.base_url + "/decisions", **kwargs
                    )
            except Exception as error:
                kind = (
                    "timeout"
                    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower()
                    else "transport"
                )
                if attempt >= self.max_retries or not _is_retryable_connection(error):
                    raise OpenAIDecisionsError(
                        f"Decisions connection failed: {error}", kind=kind, body=error
                    ) from error
            else:
                request_id = response.headers.get("x-request-id")
                try:
                    raw = response.json()
                except Exception:
                    raw = response.text
                if 200 <= response.status_code < 300:
                    return _decode(raw, snapshot, ids, request_id)
                retry_after = _retry_after_seconds(response.headers)
                if (
                    attempt >= self.max_retries
                    or response.status_code not in (408, 429)
                    and not 500 <= response.status_code < 600
                ):
                    raise OpenAIDecisionsError(
                        f"OpenAI Decisions HTTP {response.status_code}",
                        kind="http",
                        status=response.status_code,
                        body=raw,
                        request_id=request_id,
                        retry_after=retry_after,
                    )
            await asyncio.sleep(min(0.5 * 2**attempt, 5) if retry_after is None else retry_after)
        raise AssertionError("unreachable")


__all__ = ["OpenAIDecisionsClient", "OpenAIDecisionsError"]


def _normalize_base_url(value: str | None = None) -> str:
    normalized = (
        (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1" if value is None else value)
        .strip()
        .rstrip("/")
        .removesuffix("/decisions")
    )
    try:
        parsed = urlsplit(normalized)
        valid = parsed.scheme in ("http", "https") and bool(parsed.hostname)
        valid = valid and parsed.username is None and parsed.password is None
        valid = valid and not parsed.query and not parsed.fragment
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise OpenAIDecisionsError(
            "base_url must be an HTTP(S) URL without credentials, query, or fragment",
            kind="compatibility", code="openai-base-url",
        )
    return normalized


def _validate_normalized_result(raw: Any, questions: Any) -> dict[str, Any]:
    def invalid() -> Any:
        raise OpenAIDecisionsError("Invalid normalized Decisions result", kind="response", body=raw)

    if type(raw) is not dict or type(raw.get("answers")) is not dict:
        invalid()
    ids = list(questions)
    if set(raw["answers"]) != set(ids):
        invalid()
    wire = []
    for i, identifier in enumerate(ids):
        answer = raw["answers"][identifier]
        question = questions[identifier]
        if type(answer) is not dict or answer.get("type") != question["type"]:
            invalid()
        name = f"q{i}"
        if question["type"] == "noul":
            wire.append({"type": "predicate", "name": name, "probability": answer.get("noul")})
            continue
        if type(answer.get("probabilities")) is not dict:
            invalid()
        probabilities = []
        for value, probability in answer["probabilities"].items():
            if question["type"] == "score":
                if (
                    not isinstance(value, str)
                    or not value.isascii()
                    or not value.isdecimal()
                    or str(int(value)) != value
                ):
                    invalid()
                value = int(value)
            probabilities.append({"value": value, "probability": probability})
        item = {
            "type": question["type"],
            "name": name,
            "confidence": answer.get("confidence"),
            "probabilities": probabilities,
        }
        if question["type"] == "score":
            legend = {str(i): value for i, value in enumerate(question["criteria"])}
            if not is_json_value(answer.get("legend")) or canonical_json(
                answer.get("legend")
            ) != canonical_json(legend):
                invalid()
            item["score"] = answer.get("score")
        else:
            item["choice"] = answer.get("choice")
        wire.append(item)
    try:
        return _decode(
            {"model": raw.get("model"), "usage": raw.get("usage"), "answers": wire},
            questions,
            ids,
            None,
        )
    except OpenAIDecisionsError as error:
        raise OpenAIDecisionsError(str(error), kind="response", body=raw) from error


def _is_valid_decisions_answer(question: Any, answer: Any) -> bool:
    try:
        _validate_normalized_result(
            {
                "model": "cached",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "answers": {"q": answer},
            },
            {"q": question},
        )
        return True
    except (OpenAIDecisionsError, TypeError, ValueError, OverflowError):
        return False
