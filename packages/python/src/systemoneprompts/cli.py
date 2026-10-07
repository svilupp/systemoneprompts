"""Command line interface matching the TypeScript command surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from .cache import cache_stats, clear_cache, default_cache_dir
from .definition import check_definition, load_definition, parse_definition, read_source
from .diagnostics import SystemOnePromptsError, format_diagnostic, has_errors
from .evaluation import (
    EvalCaseError,
    execute_eval,
    load_eval_cases,
    preflight_eval,
    prepare_sweep,
    protect_report_path,
)
from .factors import create_factor_evaluator
from .generator import generate, render_definition
from .json_values import is_json_value, is_plain_object, js_json_dumps, js_string, parse_json
from .requirements import create_state_assert

USAGE = """systemoneprompts <command> [options]

Commands:
  check     <files...> [--strict]
  generate  <files...> [--out dir] [--check]
  run       <file> --state s.json | <stdin> [--answers a.json] [--cache] [--json] [--cache-root dir] [--base-url url] [--model name] [--provider typesafe|openai|cloudflare|openrouter]
  eval      <file> --cases cases.jsonl [--cache] [--sweep factor] [--report out.json] [--cache-root dir] [--base-url url] [--model name] [--provider typesafe|openai|cloudflare|openrouter]
  cache     stats | clear [--provider typesafe|openai|cloudflare|openrouter] [--cache-root dir] [--base-url url]
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(1)


def print_diagnostics(diagnostics: list[Any], strict: bool = False) -> int:
    errors = 0
    warnings = 0
    for item in diagnostics:
        severity = "error" if strict and item.severity == "warning" else item.severity
        if severity == "error":
            errors += 1
        else:
            warnings += 1
        print(f"{severity}: {format_diagnostic(item)}", file=sys.stderr)
    if diagnostics:
        print(f"{errors} error(s), {warnings} warning(s)", file=sys.stderr)
    return errors


def fail(message: str, code: int = 1) -> int:
    print(message, file=sys.stderr)
    return code


def _load_checked(path: str) -> Any:
    try:
        definition = load_definition(path)
    except SystemOnePromptsError as error:
        print_diagnostics(list(error.diagnostics))
        raise SystemExit(1) from error
    except OSError as error:
        raise SystemExit(fail(f"error: {path}: {error}")) from error
    diagnostics = check_definition(definition)
    print_diagnostics(diagnostics)
    if has_errors(diagnostics):
        raise SystemExit(1)
    return definition


def _parse_json(text: str, what: str) -> Any:
    try:
        return parse_json(text)
    except json.JSONDecodeError as error:
        raise SystemExit(fail(f"{what}: {error}")) from error


def _read_text(path: str) -> str:
    return read_source(path)


def _dump_json(value: Any) -> str:
    """`JSON.stringify(value, null, 2)`."""
    return js_json_dumps(value, indent=2)


def _check(paths: list[str], strict: bool) -> int:
    if not paths:
        return fail("systemoneprompts check <files...> [--strict]")
    errors = 0
    for path in paths:
        try:
            source = _read_text(path)
            definition = parse_definition(source, filename=path)
            errors += print_diagnostics(check_definition(definition), strict)
        except SystemOnePromptsError as error:
            errors += print_diagnostics(list(error.diagnostics), strict)
        except OSError as error:
            errors += 1
            print(f"error: {path}: {error}", file=sys.stderr)
    return 1 if errors else 0


def _output_path(file: str, out: str | None, *, multiple: bool) -> Path:
    name = f"{Path(file).stem}_generated.py"
    if out is None:
        return Path(file).with_name(name)
    target = Path(out)
    if multiple or target.is_dir() or target.suffix != ".py":
        return target / name
    return target


def _generate(paths: list[str], check_only: bool, out: str | None) -> int:
    if not paths:
        return fail("systemoneprompts generate <files...> [--out dir] [--check]")
    destinations: dict[str, list[str]] = {}
    multiple = len(paths) > 1
    for file in paths:
        if Path(file).suffix.lower() != ".toml":
            print(f"error: {file}: source file must have a .toml extension", file=sys.stderr)
            return 1
        target = _output_path(file, out, multiple=multiple).resolve()
        destinations.setdefault(str(target), []).append(file)
        if Path(file).resolve() == target:
            print(f"error: refusing to overwrite source file {file}", file=sys.stderr)
            return 1
    duplicates = {path: sources for path, sources in destinations.items() if len(sources) > 1}
    if duplicates:
        for path, sources in duplicates.items():
            print(f"error: duplicate output path {path} for {', '.join(sources)}", file=sys.stderr)
        return 1

    failed = 0
    for file in paths:
        try:
            source = _read_text(file)
            definition = parse_definition(source, filename=file)
        except SystemOnePromptsError as error:
            failed += 1
            print_diagnostics(list(error.diagnostics))
            continue
        except OSError as error:
            failed += 1
            print(f"error: {file}: {error}", file=sys.stderr)
            continue
        diagnostics = check_definition(definition)
        print_diagnostics(diagnostics)
        if has_errors(diagnostics):
            failed += 1
            continue
        rendered = render_definition(definition, source_name=file)
        target = _output_path(file, out, multiple=multiple)
        if check_only:
            try:
                existing = target.read_text(encoding="utf-8")
            except FileNotFoundError:
                print(f"missing generated file: {target}", file=sys.stderr)
                failed += 1
                continue
            except OSError as error:
                print(f"error: {target}: {error}", file=sys.stderr)
                failed += 1
                continue
            if existing != rendered:
                print(f"stale generated file: {target}", file=sys.stderr)
                failed += 1
            continue
        try:
            generate(definition, target, source_name=file)
            print(target)
        except OSError as error:
            failed += 1
            print(f"error: {target}: {error}", file=sys.stderr)
    return 1 if failed else 0


def _run(
    file: str | None,
    *,
    state: str | None,
    answers: str | None,
    cache: bool,
    json_output: bool,
    model: str | None,
    provider: str | None = None,
    base_url: str | None = None,
    cache_root: str | None = None,
) -> int:
    if not file:
        return fail(
            "systemoneprompts run <file> --state s.json | <stdin> [--answers a.json] [--cache] [--json] [--cache-root dir] [--base-url url] [--model name] [--provider typesafe|openai|cloudflare|openrouter]"
        )
    definition = _load_checked(file)
    try:
        state_text = sys.stdin.read() if not state or state == "-" else _read_text(state)
    except OSError as error:
        return fail(str(error))
    payload = _parse_json(state_text, state or "<stdin>")
    try:
        create_state_assert(definition.requires)(payload)
    except SystemOnePromptsError as error:
        print(str(error), file=sys.stderr)
        return 1

    if answers:
        try:
            supplied = parse_json(_read_text(answers))
        except (OSError, json.JSONDecodeError) as error:
            return fail(str(error))
        if not is_plain_object(supplied) or not is_json_value(supplied):
            return fail("answers must be a JSON object")
        try:
            factors = create_factor_evaluator(definition.factor_definitions)(supplied)
        except SystemOnePromptsError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(_dump_json({"answers": supplied, "factors": factors}))
        return 0

    from .provider import LiveClientError, create_client

    created = None
    try:
        created = create_client(definition, cache=cache, model=model, provider=provider, cache_root=cache_root, base_url=base_url)
        response = asyncio.run(
            created["client"].system_one(
                state=payload, questions=definition.questions, model=created["model"]
            )
        )
        factors = create_factor_evaluator(definition.factor_definitions)(response["answers"])
    except LiveClientError as error:
        print(str(error), file=sys.stderr)
        return 1
    except SystemOnePromptsError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        return fail(str(error))
    finally:
        if created is not None:
            for resource in {id(created["client"]): created["client"], id(created.get("raw")): created.get("raw")}.values():
                closer = getattr(resource, "close", None)
                if callable(closer):
                    closer()
    caching = created["cache"]
    cache_info = caching.stats() if caching is not None else None
    if json_output:
        output: dict[str, Any] = {
            "model": response.get("model"),
            "answers": response.get("answers"),
            "factors": factors,
            "usage": response.get("usage"),
        }
        if cache_info is not None:
            # `JSON.stringify` drops the key entirely when no cache is active.
            output["cache"] = {
                "requests": cache_info.requests,
                "hits": cache_info.hits,
                "misses": cache_info.misses,
                "keys": cache_info.keys,
            }
        print(_dump_json(output))
        return 0
    print(f"model  {_js_field(response.get('model'))}")
    if definition.meta.get("title"):
        print(f"title  {definition.meta['title']}")
    print()
    print("answers")
    for answer_id, answer in (response.get("answers") or {}).items():
        print(f"  {answer_id}")
        print(f"    {_format_answer(answer)}")
    print()
    print("factors")
    for factor_id, value in factors.items():
        print(f"  {factor_id}  {js_string(value)}")
    usage = response.get("usage") or {}
    print()
    print(
        f"usage  in={_js_field(usage.get('input_tokens'))}"
        f"  out={_js_field(usage.get('output_tokens'))}"
    )
    if cache_info:
        print(f"cache  hits={cache_info.hits}  misses={cache_info.misses}")
    return 0


def _js_field(value: Any) -> str:
    """Template-literal rendering of a possibly missing field (`undefined`)."""
    return "undefined" if value is None else js_string(value)


def _format_answer(answer: Any) -> str:
    if not isinstance(answer, dict):
        return "null" if answer is None else js_string(answer)
    if answer.get("type") == "noul":
        return f"noul={_js_field(answer.get('noul'))}"
    if answer.get("type") == "choice":
        return (
            f"choice={_js_field(answer.get('choice'))}"
            f"  confidence={_js_field(answer.get('confidence'))}"
        )
    if answer.get("type") == "score":
        return (
            f"score={_js_field(answer.get('score'))}"
            f"  confidence={_js_field(answer.get('confidence'))}"
        )
    return json.dumps(answer, ensure_ascii=False, separators=(",", ":"))


def _eval(
    file: str | None,
    *,
    cases: str | None,
    cache: bool,
    sweep: str | None,
    report: str | None,
    model: str | None,
    provider: str | None = None,
    base_url: str | None = None,
    cache_root: str | None = None,
) -> int:
    if not file or not cases:
        return fail(
            "systemoneprompts eval <file> --cases cases.jsonl [--cache] [--sweep factor] [--report out.json] [--cache-root dir] [--base-url url] [--model name] [--provider typesafe|openai|cloudflare|openrouter]"
        )
    try:
        if report:
            protect_report_path(report, file, cases)
        definition = _load_checked(file)
        loaded = load_eval_cases(_read_text(cases), cases, definition)
        sweep_plan = prepare_sweep(sweep, definition) if sweep else None
        preflight_eval(definition, loaded, sweep_plan)
    except EvalCaseError as error:
        for message in error.messages:
            print(message, file=sys.stderr)
        return fail(error.summary)
    except SystemOnePromptsError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError as error:
        return fail(str(error))

    from .provider import LiveClientError, create_client

    created = None
    try:
        created = create_client(definition, cache=cache, model=model, provider=provider, cache_root=cache_root, base_url=base_url)
        caching = created["cache"]
        result = asyncio.run(
            execute_eval(
                definition,
                loaded,
                created["client"],
                model=created["model"],
                sweep=sweep_plan,
                cache_stats=(caching.stats if caching is not None else None),
                file=file,
            )
        )
    except LiveClientError as error:
        print(str(error), file=sys.stderr)
        return 1
    except SystemOnePromptsError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        return fail(str(error))
    finally:
        if created is not None:
            for resource in {id(created["client"]): created["client"], id(created.get("raw")): created.get("raw")}.values():
                closer = getattr(resource, "close", None)
                if callable(closer):
                    closer()

    for line in result.pop("_stderr", []):
        print(line, file=sys.stderr)
    errors = int(result.get("errors") or 0)
    encoded = _dump_json(result) + "\n"
    if report:
        try:
            Path(report).write_text(encoded, encoding="utf-8")
        except OSError as error:
            return fail(str(error))
        print(report)
    else:
        print(encoded, end="")
    return 1 if errors else 0


def _cache(action: str | None, *, provider: str | None = None, cache_root: str | None = None, base_url: str | None = None) -> int:
    from .dev import cloudflare_cache_dir, openai_cache_dir
    from .provider import load_dotenv
    load_dotenv()
    selected = provider or "typesafe"
    if selected not in ("typesafe", "openai", "cloudflare", "openrouter"):
        return fail('provider-value: provider must be "typesafe", "openai", "cloudflare", or "openrouter"')
    if base_url is not None and selected == "typesafe":
        return fail("--base-url is only used for Decisions cache scope")
    try:
        if selected == "openrouter":
            from .openrouter import openrouter_cache_dir
            directory = openrouter_cache_dir(dir=cache_root, base_url=base_url)
        elif selected == "cloudflare":
            directory = cloudflare_cache_dir(dir=cache_root, base_url=base_url)
        elif selected == "openai":
            directory = openai_cache_dir(dir=cache_root, base_url=base_url)
        else:
            directory = str(Path(cache_root) / "cache") if cache_root is not None else default_cache_dir()
    except SystemOnePromptsError as error:
        return fail(format_diagnostic(error.diagnostic))
    if action == "clear":
        clear_cache(directory, root=cache_root if selected == "typesafe" else None)
        print(f"cleared {directory}")
        return 0
    if action in {None, "stats"}:
        stats = cache_stats(directory)
        print(f"dir      {directory}")
        print(f"entries  {stats['entries']}")
        for model, count in stats["models"].items():
            print(f"model    {model}  {count}")
        for row in stats["drift"]:
            requested = row.get("requested")
            reported = row.get("reported")
            if requested and requested != reported:
                print(f"drift    {requested} → {reported}  {row['count']}")
        return 0
    return fail("systemoneprompts cache stats | clear")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="systemoneprompts",
        description="Check and run portable TOML definitions",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument("--help", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--state")
    parser.add_argument("--answers")
    parser.add_argument("--cache", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cases")
    parser.add_argument("--sweep")
    parser.add_argument("--report")
    parser.add_argument("--model")
    parser.add_argument("--provider")
    parser.add_argument("--cache-root")
    parser.add_argument("--base-url")
    parser.add_argument("command", nargs="?")
    parser.add_argument("rest", nargs="*")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_intermixed_args(argv)
    if args.help:
        print(USAGE)
        return 0
    if not args.command:
        print(USAGE)
        return 1
    command = args.command
    rest = list(args.rest)
    if command == "check":
        return _check(rest, args.strict)
    if command == "generate":
        return _generate(rest, args.check, args.out)
    if command == "run":
        return _run(
            rest[0] if rest else None,
            state=args.state,
            answers=args.answers,
            cache=args.cache,
            json_output=args.json,
            model=args.model,
            provider=args.provider,
            base_url=args.base_url,
            cache_root=args.cache_root,
        )
    if command == "eval":
        return _eval(
            rest[0] if rest else None,
            cases=args.cases,
            cache=args.cache,
            sweep=args.sweep,
            report=args.report,
            model=args.model,
            provider=args.provider,
            base_url=args.base_url,
            cache_root=args.cache_root,
        )
    if command == "cache":
        return _cache(rest[0] if rest else None, provider=args.provider, cache_root=args.cache_root, base_url=args.base_url)
    return fail(f"unknown command `{command}`\n\n{USAGE}")


if __name__ == "__main__":
    raise SystemExit(main())
