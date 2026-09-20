from __future__ import annotations

import json
from pathlib import Path

from helpers import fixture, fixture_path, run_cli
from systemoneprompts.cli import main


def test_module_cli_checks_definition() -> None:
    result = run_cli(["check", str(fixture_path("golden/triage.toml"))])
    assert result.returncode == 0, result.stderr


def test_usage_failure_exits_1() -> None:
    result = run_cli([])
    assert result.returncode == 1
    assert "systemoneprompts <command>" in result.stdout


def test_help_flag_prints_usage_and_short_flag_is_unknown() -> None:
    help_result = run_cli(["--help"])
    assert help_result.returncode == 0
    assert "systemoneprompts <command>" in help_result.stdout
    command_help = run_cli(["check", "--help"])
    assert command_help.returncode == 0
    assert "systemoneprompts <command>" in command_help.stdout
    short = run_cli(["-h"])
    assert short.returncode == 1
    assert "unrecognized arguments" in short.stderr


def test_check_continues_after_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.toml"
    broken.write_text("oops = [\n", encoding="utf-8")
    missing = tmp_path / "missing.toml"
    result = run_cli(
        ["check", str(broken), str(missing), str(fixture_path("errors/unknown-option.toml"))]
    )
    assert result.returncode == 1
    assert "broken.toml" in result.stderr
    assert "missing.toml" in result.stderr
    assert "unknown option `billling`" in result.stderr


def test_strict_promotes_warnings() -> None:
    relaxed = run_cli(["check", str(fixture_path("errors/backtick-typo.toml"))])
    assert relaxed.returncode == 0
    assert "warning:" in relaxed.stderr
    strict = run_cli(["check", "--strict", str(fixture_path("errors/backtick-typo.toml"))])
    assert strict.returncode == 1
    assert "error:" in strict.stderr


def test_generate_writes_and_check_detects_staleness(tmp_path: Path) -> None:
    toml = tmp_path / "triage.toml"
    toml.write_text(fixture("golden/triage.toml"), encoding="utf-8")
    missing = run_cli(["generate", "--check", str(toml)])
    assert missing.returncode == 1
    assert "missing generated file" in missing.stderr

    written = run_cli(["generate", str(toml)])
    assert written.returncode == 0
    generated = tmp_path / "triage_generated.py"
    assert written.stdout.strip() == str(generated)
    assert generated.exists()
    assert "sha256:" in generated.read_text(encoding="utf-8")

    fresh = run_cli(["generate", "--check", str(toml)])
    assert fresh.returncode == 0

    toml.write_text(fixture("golden/triage.toml") + "\n# touched\n", encoding="utf-8")
    stale = run_cli(["generate", "--check", str(toml)])
    assert stale.returncode == 1
    assert "stale generated file" in stale.stderr

    out = tmp_path / "out"
    moved = run_cli(["generate", "--out", str(out), str(toml)])
    assert moved.returncode == 0
    assert "questions" in (out / "triage_generated.py").read_text(encoding="utf-8")


def test_generate_continues_after_source_read_errors(tmp_path: Path) -> None:
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"
    first.write_text(fixture("golden/noul-string.toml"), encoding="utf-8")
    second.write_text(fixture("golden/noul-string.toml"), encoding="utf-8")
    result = run_cli(["generate", str(first), str(tmp_path / "missing.toml"), str(second)])
    assert result.returncode == 1
    assert "first_generated.py" in result.stdout
    assert "second_generated.py" in result.stdout
    assert "missing.toml" in result.stderr


def test_generate_rejects_non_toml_and_duplicate_outputs(tmp_path: Path) -> None:
    source = tmp_path / "definition.txt"
    source.write_text(fixture("golden/noul-string.toml"), encoding="utf-8")
    result = run_cli(["generate", str(source)])
    assert result.returncode == 1
    assert ".toml extension" in result.stderr

    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "same.toml").write_text(fixture("golden/noul-string.toml"), encoding="utf-8")
    (right / "same.toml").write_text(fixture("golden/noul-string.toml"), encoding="utf-8")
    out = tmp_path / "out"
    duplicate = run_cli(
        ["generate", "--out", str(out), str(left / "same.toml"), str(right / "same.toml")]
    )
    assert duplicate.returncode == 1
    assert "duplicate output path" in duplicate.stderr
    assert not (out / "same_generated.py").exists()


def test_generate_check_does_not_use_fixed_scratch_file(tmp_path: Path) -> None:
    generated = tmp_path / "definition_generated.py"
    result = run_cli(
        ["generate", str(fixture_path("golden/noul-string.toml")), "--out", str(generated)]
    )
    assert result.returncode == 0, result.stderr
    check = run_cli(
        [
            "generate",
            "--check",
            str(fixture_path("golden/noul-string.toml")),
            "--out",
            str(generated),
        ]
    )
    assert check.returncode == 0, check.stderr
    assert not (Path.cwd() / ".systemoneprompts-generated-preview.py").exists()


def test_run_answers_is_offline(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    answers = tmp_path / "answers.json"
    state.write_text('{"ticket": {"message": "hello"}}', encoding="utf-8")
    answers.write_text(
        '{"topic": {"choice": "billing"}, "urgent": {"noul": 0.8}}',
        encoding="utf-8",
    )
    result = run_cli(
        [
            "run",
            str(Path(__file__).resolve().parents[1] / "conformance" / "v1" / "cases" / "basic" / "definition.toml"),
            "--state",
            str(state),
            "--answers",
            str(answers),
        ]
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["factors"]["route"] is True


def test_run_invalid_state_fails_before_provider() -> None:
    result = run_cli(
        ["run", str(fixture_path("golden/triage.toml"))],
        stdin='{"ticket": {"message": 42}}',
    )
    assert result.returncode == 1
    assert "ticket.message: expected string, got number" in result.stderr


def test_run_malformed_state_names_the_source() -> None:
    result = run_cli(["run", str(fixture_path("golden/triage.toml"))], stdin="{ nope")
    assert result.returncode == 1
    assert "<stdin>:" in result.stderr
    nonstandard = run_cli(["run", str(fixture_path("golden/triage.toml"))], stdin="NaN")
    assert nonstandard.returncode == 1
    assert "not valid JSON" in nonstandard.stderr or "NaN" in nonstandard.stderr


def test_eval_rejects_malformed_cases_before_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "systemoneprompts.provider.create_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider")),
    )
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        json.dumps(
            {
                "id": 42,
                "state": 3,
                "labels": {"missing": True},
                "factors": {"topic.billing": "yes"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_cli(["eval", str(fixture_path("golden/triage.toml")), "--cases", str(cases)])
    assert result.returncode == 1
    assert "unknown question id" in result.stderr
    assert "4 invalid eval case error(s)" in result.stderr


def test_eval_rejects_report_overwrite(tmp_path: Path) -> None:
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({"state": {}}) + "\n", encoding="utf-8")
    result = run_cli(
        [
            "eval",
            str(fixture_path("golden/triage.toml")),
            "--cases",
            str(cases),
            "--report",
            str(cases),
        ]
    )
    assert result.returncode == 1
    assert "must not overwrite the definition or cases input" in result.stderr


def test_eval_partial_report_with_fake_client(tmp_path: Path, monkeypatch) -> None:
    from systemoneprompts.provider import FakeClient

    state = {
        "ticket": {"message": "ok", "sender": {"email": "a@b.c", "display_name": "A"}},
        "customer": {"open_orders": []},
        "policy": {"sensitive_credentials": []},
    }

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
    monkeypatch.setattr(
        "systemoneprompts.provider.create_client",
        lambda *_args, **_kwargs: {"client": client, "model": "jev-test", "cache": None},
    )
    cases = tmp_path / "cases.jsonl"
    report = tmp_path / "report.json"
    report.write_text("stale report\n", encoding="utf-8")
    cases.write_text(
        json.dumps({"id": "ok", "state": state, "labels": {"topic": "billing"}})
        + "\n"
        + json.dumps(
            {
                "id": "bad-api",
                "state": {**state, "ticket": {**state["ticket"], "message": "fail"}},
                "labels": {"topic": "billing"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = main(
        [
            "eval",
            str(fixture_path("golden/triage.toml")),
            "--cases",
            str(cases),
            "--report",
            str(report),
        ]
    )
    assert result == 1
    output = json.loads(report.read_text(encoding="utf-8"))
    assert output["cases"] == 2
    assert output["errors"] == 1
    assert output["questions"]["topic"]["correct"] == 1
    # `JSON.stringify` omits `cache` when no cache is active.
    assert "cache" not in output


def test_run_output_matches_javascript_rendering(tmp_path: Path, monkeypatch, capsys) -> None:
    from systemoneprompts.provider import FakeClient

    def handler(request: dict[str, object]) -> dict[str, object]:
        answers: dict[str, object] = {}
        for qid, question in request["questions"].items():  # type: ignore[union-attr]
            if question["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": 1.0}
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
                    "score": 2.0,
                    "confidence": 0.7,
                    "legend": {"0": "Calm", "1": "Civil", "2": "Angry"},
                    "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
                }
        return {"model": "jev-test", "answers": answers, "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(
        "systemoneprompts.provider.create_client",
        lambda *_args, **_kwargs: {"client": FakeClient(handler), "model": "jev-test", "cache": None},
    )
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "ticket": {"message": "héllo", "sender": {"email": "a@b.c", "display_name": "A"}},
                "customer": {"open_orders": []},
                "policy": {"sensitive_credentials": []},
            }
        ),
        encoding="utf-8",
    )
    definition = str(fixture_path("golden/triage.toml"))

    assert main(["run", definition, "--state", str(state)]) == 0
    human = capsys.readouterr().out
    assert "noul=1\n" in human  # JavaScript prints `1`, not `1.0`
    assert "score=2  confidence=0.7" in human
    assert "  true" in human and "True" not in human

    assert main(["run", definition, "--state", str(state), "--json"]) == 0
    raw = capsys.readouterr().out
    assert "cache" not in json.loads(raw)
    assert "\\u" not in raw  # non-ASCII is emitted literally like `JSON.stringify`


def test_cache_clear_is_restricted_to_cache_dir(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / ".systemoneprompts" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "x.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = run_cli(["cache", "clear"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert not cache_dir.exists()


def test_cli_does_not_abbreviate_options() -> None:
    result = run_cli(["run", str(fixture_path("golden/triage.toml")), "--sta", "-"])
    assert result.returncode == 1
    assert "unrecognized arguments" in result.stderr


def test_main_unknown_command() -> None:
    assert main(["nope"]) == 1
