#!/usr/bin/env python3
"""Explicit live matrix for both source packages; never part of offline checks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = (
    "TYPESAFE_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "CLOUDFLARE_API_TOKEN",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--require-credentials", action="store_true",
        help="Fail when any selected provider lacks credentials",
    )
    parser.add_argument(
        "--cloudflare-token-alias",
        action="store_true",
        help="Use local CLOUDFLARE_API_KEY as a bearer token when API_TOKEN is absent",
    )
    parser.add_argument("--language", choices=("typescript", "python"))
    parser.add_argument(
        "--variation",
        choices=(
            "environment",
            "explicit",
            "cli",
            "text",
            "stdin",
            "text-simple",
            "json-structured",
        ),
        action="append",
        help="Run only selected variations; repeat to select more than one",
    )
    parser.add_argument(
        "--provider", choices=("typesafe", "openai", "openrouter", "cloudflare", "cloudflare-jev"),
        help="Run only one provider"
    )
    args = parser.parse_args()
    env = dict(os.environ)
    for filename in (ROOT / ".env",):
        if filename.exists():
            for line in filename.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    key, value = line.split("=", 1)
                    env.setdefault(key.strip(), value.strip().strip("\"'"))
    if args.cloudflare_token_alias and not env.get("CLOUDFLARE_API_TOKEN"):
        env["CLOUDFLARE_API_TOKEN"] = env.get("CLOUDFLARE_API_KEY", "")
    env["UV_NO_CONFIG"] = "1"
    fixture = json.loads(
        (ROOT / "conformance/v1/providers/openrouter-decisions.json").read_text()
    )
    account = env.get("CLOUDFLARE_ACCOUNT_ID", "missing")
    models = [
        ("typesafe", "jev-latest", "TYPESAFE_API_KEY", "https://api.typesafe.ai"),
        ("typesafe", "jev-1.13.0", "TYPESAFE_API_KEY", "https://api.typesafe.ai"),
        ("openai", "gpt-6-luna", "OPENAI_API_KEY", "https://api.openai.com/v1"),
        (
            "openrouter",
            "~typesafe/jev-latest",
            "OPENROUTER_API_KEY",
            "https://openrouter.ai/api/alpha",
        ),
        (
            "openrouter",
            "typesafe/jev-1.13",
            "OPENROUTER_API_KEY",
            "https://openrouter.ai/api/alpha",
        ),
        (
            "openrouter",
            "openai/gpt-6-luna-decisions",
            "OPENROUTER_API_KEY",
            "https://openrouter.ai/api/alpha",
        ),
        (
            "cloudflare",
            "clef",
            "CLOUDFLARE_API_TOKEN",
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run",
        ),
        (
            "cloudflare",
            "clef-flash",
            "CLOUDFLARE_API_TOKEN",
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run",
        ),
        (
            "cloudflare",
            "@cf/cloudflare/clef",
            "CLOUDFLARE_API_TOKEN",
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run",
        ),
        (
            "cloudflare",
            "@cf/cloudflare/clef-flash",
            "CLOUDFLARE_API_TOKEN",
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run",
        ),
        ("cloudflare-jev", "jev-latest", "CLOUDFLARE_API_TOKEN", None),
    ]
    secrets = [env[k] for k in (*KEYS, "CLOUDFLARE_API_KEY") if env.get(k)]

    def redact(text):
        for secret in secrets:
            text = text.replace(secret, "[redacted]")
        return text

    def command(language):
        if language == "typescript":
            return ["bun", str(ROOT / "packages/typescript/src/cli/index.ts")]
        return [
            "uv",
            "run",
            "--locked",
            "--project",
            str(ROOT / "packages/python"),
            "systemoneprompts",
        ]

    def run_language(language):
        rows = []
        for index, (provider, model, key, base) in enumerate(models):
            if args.provider and provider != args.provider:
                continue
            source = dict(env)
            for name in (
                "TYPESAFE_BASE_URL",
                "TYPESAFE_MODEL",
                "TYPESAFE_DEFAULT_MODEL",
                "OPENAI_BASE_URL",
                "OPENROUTER_BASE_URL",
            ):
                source.pop(name, None)
            if provider not in ("cloudflare", "cloudflare-jev", "openrouter"):
                source.pop("CLOUDFLARE_ACCOUNT_ID", None)
            for mode in args.variation or (
                "environment",
                "explicit",
                "text-simple" if provider == "cloudflare-jev" else "text",
                "cli",
                "stdin",
            ):
                row = {
                    "language": language,
                    "provider": provider,
                    "model": model,
                    "variation": mode,
                }
                if not source.get(key) or (
                    provider.startswith("cloudflare")
                    and not source.get("CLOUDFLARE_ACCOUNT_ID")
                ):
                    row.update(
                        status="skip",
                        reason="Required provider credentials unavailable",
                    )
                    rows.append(row)
                    continue
                started = time.monotonic()
                try:
                    with tempfile.TemporaryDirectory(
                        prefix="live-matrix-"
                    ) as temporary:
                        cwd = Path(temporary)
                        if mode not in ("cli", "stdin"):
                            if (
                                mode == "environment"
                                and base
                                and provider in ("typesafe", "openai", "openrouter")
                            ):
                                source[
                                    {
                                        "typesafe": "TYPESAFE_BASE_URL",
                                        "openai": "OPENAI_BASE_URL",
                                        "openrouter": "OPENROUTER_BASE_URL",
                                    }[provider]
                                ] = base
                            config = {
                                "provider": provider,
                                "model": model,
                                "key": key,
                                "baseURL": base + "/decisions/"
                                if mode == "explicit"
                                and provider in ("openrouter", "openai")
                                else base,
                                "mode": mode,
                                "state": fixture["state"],
                                "questions": fixture["questions"],
                            }
                            if mode in ("text", "text-simple", "json-structured"):
                                if mode != "json-structured":
                                    config["state"] = json.dumps(fixture["state"])
                                config["questions"] = json.loads(
                                    json.dumps(fixture["questions"])
                                )
                                if mode != "text-simple":
                                    config["questions"]["frustration"]["criteria"][
                                        1
                                    ] = {"description": "Frustrated"}
                            if language == "typescript":
                                cmd = [
                                    "bun",
                                    str(
                                        ROOT
                                        / "packages/typescript/live/provider-probe.ts"
                                    ),
                                ]
                            else:
                                cmd = [
                                    "uv",
                                    "run",
                                    "--locked",
                                    "--project",
                                    str(ROOT / "packages/python"),
                                    "python",
                                    str(
                                        ROOT / "packages/python/live/provider_probe.py"
                                    ),
                                ]
                            result = subprocess.run(
                                cmd,
                                input=json.dumps(config),
                                text=True,
                                capture_output=True,
                                env=source,
                                cwd=cwd,
                                timeout=50,
                                check=False,
                            )
                            try:
                                row.update(json.loads(redact(result.stdout)))
                            except ValueError:
                                row.update(
                                    status="fail",
                                    message=redact(result.stdout + result.stderr)[
                                        -2000:
                                    ],
                                )
                        else:
                            selected = (
                                "typesafe" if provider == "cloudflare-jev" else provider
                            )
                            # TOML endpoint + CLI model/provider for half the cases; CLI endpoint for the rest.
                            header = f'provider = "{selected}"\nmodel = "{model}"\n'
                            if base and index % 2 == 0:
                                header += f'base_url = "{base}"\n'
                            definition = cwd / "decisions.toml"
                            text = header
                            for name, question in fixture["questions"].items():
                                text += f'\n[questions.{name}]\ntype = "{question["type"]}"\n'
                                instructions = question["instructions"]
                                if isinstance(instructions, dict):
                                    text += 'instructions = { task = "Which team should handle this?" }\n'
                                else:
                                    text += (
                                        f"instructions = {json.dumps(instructions)}\n"
                                    )
                                criteria = question["criteria"]
                                if isinstance(criteria, dict):
                                    text += (
                                        "criteria = { "
                                        + ", ".join(
                                            f"{json.dumps(k)} = {json.dumps(v)}"
                                            for k, v in criteria.items()
                                        )
                                        + " }\n"
                                    )
                                else:
                                    text += f"criteria = {json.dumps(criteria)}\n"
                            definition.write_text(text)
                            (cwd / "state.json").write_text(
                                json.dumps(fixture["state"])
                            )
                            (cwd / "cases.jsonl").write_text(
                                json.dumps({"state": fixture["state"]}) + "\n"
                            )
                            flags = [
                                "--provider",
                                selected,
                                "--model",
                                model,
                                "--cache",
                                "--cache-root",
                                str(cwd / "records"),
                            ]
                            if base and index % 2:
                                flags += ["--base-url", base]
                            prefix = command(language)
                            outputs = []
                            for _ in range(2):
                                result = subprocess.run(
                                    [
                                        *prefix,
                                        "run",
                                        str(definition),
                                        *(
                                            []
                                            if mode == "stdin"
                                            else ["--state", str(cwd / "state.json")]
                                        ),
                                        "--json",
                                        *flags,
                                    ],
                                    input=json.dumps(fixture["state"])
                                    if mode == "stdin"
                                    else None,
                                    text=True,
                                    capture_output=True,
                                    cwd=cwd,
                                    env=source,
                                    timeout=50,
                                    check=False,
                                )
                                if result.returncode:
                                    raise RuntimeError(
                                        redact(result.stdout + result.stderr)[-2000:]
                                    )
                                outputs.append(json.loads(result.stdout))
                            assert outputs[0]["answers"] == outputs[1]["answers"], (
                                "Cache changed answers"
                            )
                            assert outputs[1]["usage"] == {
                                "input_tokens": 0,
                                "output_tokens": 0,
                            }, "CLI cache miss"
                            result = subprocess.run(
                                [
                                    *prefix,
                                    "eval",
                                    str(definition),
                                    "--cases",
                                    str(cwd / "cases.jsonl"),
                                    "--report",
                                    str(cwd / "eval.json"),
                                    *flags,
                                ],
                                text=True,
                                capture_output=True,
                                cwd=cwd,
                                env=source,
                                timeout=50,
                                check=False,
                            )
                            if result.returncode:
                                raise RuntimeError(
                                    redact(result.stdout + result.stderr)[-2000:]
                                )
                            scope = [
                                "--provider",
                                selected,
                                "--cache-root",
                                str(cwd / "records"),
                            ]
                            if base and selected != "typesafe":
                                scope += ["--base-url", base]
                            for action in ("stats", "clear"):
                                result = subprocess.run(
                                    [*prefix, "cache", action, *scope],
                                    text=True,
                                    capture_output=True,
                                    cwd=cwd,
                                    env=source,
                                    timeout=15,
                                    check=False,
                                )
                                if result.returncode:
                                    raise RuntimeError(
                                        redact(result.stdout + result.stderr)[-2000:]
                                    )
                            row.update(
                                status="pass",
                                modelReported=outputs[0]["model"],
                                usage=outputs[0]["usage"],
                                checks=[
                                    "run",
                                    "all-hit run",
                                    "eval",
                                    "cache stats",
                                    "cache clear",
                                ],
                            )
                except (
                    AssertionError,
                    RuntimeError,
                    OSError,
                    ValueError,
                    KeyError,
                    subprocess.TimeoutExpired,
                ) as error:
                    row.update(status="fail", message=redact(str(error)))
                row["seconds"] = round(time.monotonic() - started, 3)
                rows.append(row)
                print(
                    f"{language}: {provider} {model} {mode}: {row['status']}",
                    flush=True,
                )
        return rows

    languages = [args.language] if args.language else ["typescript", "python"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        rows = [row for group in executor.map(run_language, languages) for row in group]
    report = {
        "date": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "summary": {
            status: sum(row["status"] == status for row in rows)
            for status in ("pass", "fail", "skip")
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"]), flush=True)
    return int(report["summary"]["fail"] > 0 or (args.require_credentials and report["summary"]["skip"] > 0))


if __name__ == "__main__":
    raise SystemExit(main())
