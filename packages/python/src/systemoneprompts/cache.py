"""Per-question System One cache. Optional; keep out of the pure import path."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .answers import is_answer_for_question, is_answer_shape
from .json_values import (
    canonical_json,
    is_plain_object,
    js_json_dumps,
    parse_json,
)

CacheMode = Literal["read-write", "read-only", "refresh"]
SYSTEMONE_PATH = "/v1/systemone"
_is_answer_for_question = is_answer_for_question
_is_answer_shape = is_answer_shape


@dataclass
class FetchResponse:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    status_text: str = "OK"

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8")


FetchHandler = Callable[[str, Mapping[str, Any] | None], FetchResponse]


@dataclass
class CacheStats:
    requests: int = 0
    hits: int = 0
    misses: int = 0
    keys: list[str] = field(default_factory=list)


@dataclass
class CachedEntry:
    hash: str
    reported_model: str
    answer: Any
    requested_model: str | None = None


class CacheMissError(RuntimeError):
    def __init__(self, ids: list[str]) -> None:
        listed = ", ".join(f"`{item}`" for item in ids)
        super().__init__(f"cache miss in read-only mode: {listed}")
        self.ids = ids


class CachingFetch:
    def __init__(self, handler: Callable[[str, Mapping[str, Any] | None], FetchResponse], directory: str) -> None:
        self._handler = handler
        self.dir = directory
        self._stats = CacheStats()

    def __call__(self, url: str, init: Mapping[str, Any] | None = None) -> FetchResponse:
        return self._handler(url, init)

    def stats(self) -> CacheStats:
        return CacheStats(
            requests=self._stats.requests,
            hits=self._stats.hits,
            misses=self._stats.misses,
            keys=list(self._stats.keys),
        )


def default_cache_dir(cwd: str | None = None) -> str:
    return str(Path(cwd or os.getcwd()) / ".systemoneprompts" / "cache")


def question_hash(parts: Mapping[str, Any]) -> str:
    # Key is `(model, id, state, question)`. Question *bodies* can be identical
    # across ids; `id` keeps those entries from colliding. State is the request
    # state as sent — callers that need inspect-isolation send separate requests.
    # JS `JSON.stringify` omits `undefined` (`model` when absent) but keeps `null` state.
    payload = {
        key: value
        for key, value in parts.items()
        if (key != "model" or value is not None) and (key != "id" or value is not None)
    }
    import hashlib

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def create_caching_fetch(
    *,
    dir: str | None = None,
    mode: CacheMode = "read-write",
    fetch: FetchHandler | None = None,
    validate_entry: Callable[[Any, Any], bool] | None = None,
) -> CachingFetch:
    """Cache System One answers per ``(model, id, state, question)``.

    Question *bodies* can be identical across ids; ``id`` keeps those entries
    from colliding. ``state`` is the request state as sent — callers that need
    inspect-isolation send separate requests.
    """
    directory = dir or default_cache_dir()
    base_fetch = fetch or _stdlib_fetch
    stats = CacheStats()

    def handler(url: str, init: Mapping[str, Any] | None = None) -> FetchResponse:
        options = dict(init or {})
        method = str(options.get("method") or "GET").upper()
        body = options.get("body")
        if not _is_system_one_request(url, method) or not isinstance(body, str):
            return _forward(base_fetch, url, options)
        try:
            parsed = parse_json(body)
        except (ValueError, RecursionError):
            return _forward(base_fetch, url, options)
        if not is_plain_object(parsed) or not is_plain_object(parsed.get("questions")):
            return _forward(base_fetch, url, options)

        model = parsed["model"] if isinstance(parsed.get("model"), str) else None
        # An absent `state` key hashes differently from `state: null` (JS `undefined`
        # is omitted by `JSON.stringify`); preserve that distinction for shared caches.
        hash_base: dict[str, Any] = {"model": model}
        if "state" in parsed:
            hash_base["state"] = parsed["state"]
        questions = parsed["questions"]
        ids = list(questions)
        hits: dict[str, CachedEntry] = {}
        misses: dict[str, Any] = {}
        for question_id in ids:
            question = questions[question_id]
            digest = question_hash({**hash_base, "id": question_id, "question": question})
            if mode == "refresh":
                misses[question_id] = question
                continue
            cached = _read_entry(directory, digest, question)
            if cached and (validate_entry is None or validate_entry(question, cached.answer)):
                hits[question_id] = cached
            else:
                misses[question_id] = question

        miss_ids = list(misses)
        stats.requests += 1
        stats.hits += len(ids) - len(miss_ids)
        stats.misses += len(miss_ids)
        stats.keys = list(ids)

        if not miss_ids:
            payload = {
                "model": _first_reported_model(hits) or model or "jev-latest",
                "answers": {question_id: hits[question_id].answer for question_id in ids},
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }
            return _json_response(payload)

        if mode == "read-only":
            raise CacheMissError(miss_ids)

        live_options = dict(options)
        live_options["body"] = js_json_dumps({**parsed, "questions": misses})
        # The body changed, so a caller-supplied Content-Length is stale; the
        # underlying fetch recomputes it (a wrong value truncates or hangs the send).
        live_options["headers"] = {
            key: value
            for key, value in dict(options.get("headers") or {}).items()
            if str(key).lower() != "content-length"
        }
        response = _forward(base_fetch, url, live_options)
        if response.status < 200 or response.status >= 300:
            return response

        result: dict[str, Any] | None = None
        answers: dict[str, Any] | None = None
        try:
            parsed_result = parse_json(response.body.decode("utf-8"))
            if is_plain_object(parsed_result):
                result = parsed_result
                if is_plain_object(parsed_result.get("answers")):
                    answers = parsed_result["answers"]
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed_result = None

        valid_live: dict[str, Any] = {}
        if answers:
            for question_id in miss_ids:
                if question_id in answers and _is_answer_for_question(
                    misses[question_id], answers[question_id]
                ):
                    if validate_entry is None or validate_entry(misses[question_id], answers[question_id]):
                        valid_live[question_id] = answers[question_id]

        all_misses_valid = all(question_id in valid_live for question_id in miss_ids)
        if not all_misses_valid and not hits:
            return response

        reported_model = (
            (result.get("model") if result and isinstance(result.get("model"), str) else None)
            or _first_reported_model(hits)
            or model
            or "jev-latest"
        )
        for question_id, answer in valid_live.items():
            digest = question_hash({**hash_base, "id": question_id, "question": misses[question_id]})
            entry = CachedEntry(
                hash=digest,
                requested_model=model,
                reported_model=reported_model,
                answer=answer,
            )
            _write_entry(directory, digest, entry)
            hits[question_id] = entry

        usage = (
            result.get("usage")
            if result and is_plain_object(result.get("usage"))
            else {"input_tokens": 0, "output_tokens": 0}
        )
        merged: dict[str, Any] = {}
        for question_id in ids:
            if question_id in hits:
                merged[question_id] = hits[question_id].answer
            elif question_id in valid_live:
                merged[question_id] = valid_live[question_id]
        return _json_response(
            {"model": reported_model, "answers": merged, "usage": usage},
            status=response.status,
            status_text=response.status_text,
            headers=response.headers,
        )

    caching = CachingFetch(handler, directory)
    caching._stats = stats
    return caching


def cache_stats(directory: str | None = None) -> dict[str, Any]:
    path = directory or default_cache_dir()
    models: dict[str, int] = {}
    drift_map: dict[str, dict[str, Any]] = {}
    entries = 0
    for file in _list_entries(path):
        digest = Path(file).stem
        raw = _read_entry_file(file, digest)
        if raw is None:
            continue
        entries += 1
        reported = raw.reported_model
        models[reported] = models.get(reported, 0) + 1
        key = json.dumps([raw.requested_model, reported])
        existing = drift_map.get(key) or {
            "requested": raw.requested_model,
            "reported": reported,
            "count": 0,
        }
        existing["count"] += 1
        drift_map[key] = existing
    drift = []
    for row in drift_map.values():
        item = {"reported": row["reported"], "count": row["count"]}
        if row["requested"] is not None:
            item["requested"] = row["requested"]
        drift.append(item)
    return {"entries": entries, "models": models, "drift": drift}


def clear_cache(directory: str | None = None, *, root: str | None = None) -> None:
    path = Path(directory or default_cache_dir()).resolve()
    provider_scope = (len(path.parts) >= 6 and path.parts[-5:-2] in (("providers", "openrouter-decisions", "v1"), ("providers", "openai-decisions", "v1"), ("providers", "cloudflare-decisions", "v1"))
                      and len(path.parts[-2]) == 64 and all(c in "0123456789abcdef" for c in path.parts[-2]))
    if path.name != "cache" or not (".systemoneprompts" in path.parts or provider_scope or (root is not None and path == (Path(root) / "cache").resolve())):
        raise RuntimeError(f"refusing to clear unexpected cache directory {path}")
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def _forward(base: FetchHandler | None, url: str, init: Mapping[str, Any]) -> FetchResponse:
    if base is None:
        raise RuntimeError("no underlying fetch is configured")
    return base(url, init)


def transport_headers(options: Mapping[str, Any]) -> dict[str, str]:
    """Request headers for an underlying HTTP client, which recomputes Content-Length."""
    return {
        str(key): str(value)
        for key, value in dict(options.get("headers") or {}).items()
        if str(key).lower() != "content-length"
    }


def _stdlib_fetch(url: str, init: Mapping[str, Any] | None = None) -> FetchResponse:
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    options = dict(init or {})
    method = str(options.get("method") or "GET").upper()
    body = options.get("body")
    headers = transport_headers(options)
    data: bytes | None
    if isinstance(body, bytes):
        data = body
    elif isinstance(body, str):
        data = body.encode("utf-8")
    else:
        data = None
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request) as response:
            return FetchResponse(
                status=int(response.status),
                status_text=getattr(response, "reason", "OK") or "OK",
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.read(),
            )
    except HTTPError as error:
        return FetchResponse(
            status=int(error.code),
            status_text=error.reason or "Error",
            headers={key.lower(): value for key, value in dict(error.headers or {}).items()},
            body=error.read() if error.fp is not None else b"",
        )


def _is_system_one_request(url: str, method: str) -> bool:
    if method != "POST":
        return False
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.path.endswith((SYSTEMONE_PATH, "/decisions"))
    except ValueError:
        return SYSTEMONE_PATH in url or "/decisions" in url


def _json_response(
    body: Any,
    status: int = 200,
    status_text: str = "OK",
    headers: Mapping[str, str] | None = None,
) -> FetchResponse:
    response_headers = {key.lower(): value for key, value in dict(headers or {}).items()}
    for stale in ("content-length", "content-encoding", "transfer-encoding"):
        response_headers.pop(stale, None)
        response_headers.pop(stale.title(), None)
        response_headers.pop(stale.upper(), None)
    # Drop any case variant.
    response_headers = {
        key: value
        for key, value in response_headers.items()
        if key.lower() not in {"content-length", "content-encoding", "transfer-encoding"}
    }
    if not any(key.lower() == "content-type" for key in response_headers):
        response_headers["content-type"] = "application/json"
    return FetchResponse(
        status=status,
        status_text=status_text,
        headers=response_headers,
        body=js_json_dumps(body).encode("utf-8"),
    )


def _first_reported_model(hits: Mapping[str, CachedEntry]) -> str | None:
    for entry in hits.values():
        if entry.reported_model:
            return entry.reported_model
    return None


def _entry_path(directory: str, digest: str) -> Path:
    return Path(directory) / digest[:2] / f"{digest}.json"


def _list_entries(directory: str) -> list[str]:
    root = Path(directory)
    if not root.is_dir():
        return []
    output: list[str] = []
    for shard in root.iterdir():
        if not shard.is_dir():
            continue
        for file in shard.iterdir():
            if file.suffix == ".json":
                output.append(str(file))
    return output


def _read_entry(directory: str, digest: str, question: Any) -> CachedEntry | None:
    return _read_entry_file(str(_entry_path(directory, digest)), digest, question)


def _read_entry_file(file: str, digest: str, question: Any | None = None) -> CachedEntry | None:
    try:
        # Same tolerance as `JSON.parse(readFileSync(file, "utf8"))`: undecodable
        # bytes become U+FFFD, and any unparsable or absurdly nested file is a miss.
        raw = parse_json(Path(file).read_bytes().decode("utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return None
    if not _is_cached_entry(raw, digest, question):
        return None
    assert is_plain_object(raw)
    return CachedEntry(
        hash=str(raw["hash"]),
        reported_model=str(raw["reportedModel"]),
        answer=raw["answer"],
        requested_model=raw.get("requestedModel") if "requestedModel" in raw else None,
    )


def _is_cached_entry(value: Any, digest: str, question: Any | None = None) -> bool:
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        return False
    if not is_plain_object(value) or value.get("hash") != digest:
        return False
    reported = value.get("reportedModel")
    if not isinstance(reported, str) or not reported:
        return False
    if "requestedModel" in value and not isinstance(value.get("requestedModel"), str):
        return False
    if "answer" not in value or not _is_answer_shape(value["answer"]):
        return False
    if question is not None and not _is_answer_for_question(question, value["answer"]):
        return False
    return True


def _write_entry(directory: str, digest: str, entry: CachedEntry) -> None:
    path = _entry_path(directory, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same field order and text as the TypeScript `JSON.stringify(entry, null, 2)`.
    payload: dict[str, Any] = {"hash": entry.hash}
    if entry.requested_model is not None:
        payload["requestedModel"] = entry.requested_model
    payload["reportedModel"] = entry.reported_model
    payload["answer"] = entry.answer
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(js_json_dumps(payload, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


__all__ = [
    "CacheMissError",
    "CacheMode",
    "CacheStats",
    "CachedEntry",
    "CachingFetch",
    "FetchHandler",
    "FetchResponse",
    "cache_stats",
    "clear_cache",
    "create_caching_fetch",
    "default_cache_dir",
    "question_hash",
    "transport_headers",
]
