import { afterAll, describe, expect, test } from "bun:test";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { cli, fixture, fixturePath } from "./helpers.ts";

describe("systemoneprompts check", () => {
  test("passes a clean file and exits 0", () => {
    const result = cli(["check", fixturePath("golden/triage.toml")]);
    expect(result.exitCode).toBe(0);
    expect(result.stderr).toBe("");
  });

  test("reports every file, keeps going after a syntax error, exits 1", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-"));
    const broken = join(dir, "broken.toml");
    const missing = join(dir, "missing.toml");
    await writeFile(broken, "oops = [");
    const result = cli(["check", broken, missing, fixturePath("errors/unknown-option.toml")]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("broken.toml:1");
    expect(result.stderr).toContain("missing.toml");
    expect(result.stderr).toContain("unknown option `billling`");
  });

  test("--strict promotes warnings", () => {
    const relaxed = cli(["check", fixturePath("errors/backtick-typo.toml")]);
    expect(relaxed.exitCode).toBe(0);
    expect(relaxed.stderr).toContain("warning:");
    const strict = cli(["check", "--strict", fixturePath("errors/backtick-typo.toml")]);
    expect(strict.exitCode).toBe(1);
    expect(strict.stderr).toContain("error:");
  });
});

describe("systemoneprompts generate", () => {
  test("writes beside the source and --check detects staleness", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-"));
    const toml = join(dir, "triage.toml");
    await writeFile(toml, fixture("golden/triage.toml"));

    const missing = cli(["generate", "--check", toml]);
    expect(missing.exitCode).toBe(1);
    expect(missing.stderr).toContain("missing generated file");

    const written = cli(["generate", toml]);
    expect(written.exitCode).toBe(0);
    expect(written.stdout.trim()).toBe(join(dir, "triage.generated.ts"));

    const fresh = cli(["generate", "--check", toml]);
    expect(fresh.exitCode).toBe(0);

    await writeFile(toml, `${fixture("golden/triage.toml")}\n# touched\n`);
    const stale = cli(["generate", "--check", toml]);
    expect(stale.exitCode).toBe(1);
    expect(stale.stderr).toContain("stale generated file");

    const out = join(dir, "out");
    const moved = cli(["generate", "--out", out, toml]);
    expect(moved.exitCode).toBe(0);
    expect(await readFile(join(out, "triage.generated.ts"), "utf8")).toContain(
      "export const questions",
    );
  });

  test("continues after source read errors", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-"));
    const first = join(dir, "first.toml");
    const missing = join(dir, "missing.toml");
    const second = join(dir, "second.toml");
    await writeFile(first, fixture("golden/noul-string.toml"));
    await writeFile(second, fixture("golden/noul-string.toml"));

    const result = cli(["generate", first, missing, second]);
    expect(result.exitCode).toBe(1);
    expect(result.stdout).toContain(join(dir, "first.generated.ts"));
    expect(result.stdout).toContain(join(dir, "second.generated.ts"));
    expect(result.stderr).toContain("missing.toml");
  });

  test("rejects non-TOML sources before writing", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-"));
    const source = join(dir, "definition.txt");
    await writeFile(source, fixture("golden/noul-string.toml"));

    const result = cli(["generate", source]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain(".toml extension");
    expect(await Bun.file(source).exists()).toBe(true);
  });

  test("detects duplicate --out paths before writing", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-"));
    const left = join(dir, "left");
    const right = join(dir, "right");
    const out = join(dir, "out");
    await Bun.write(join(left, "same.toml"), fixture("golden/noul-string.toml"));
    await Bun.write(join(right, "same.toml"), fixture("golden/noul-string.toml"));

    const result = cli([
      "generate",
      "--out",
      out,
      join(left, "same.toml"),
      join(right, "same.toml"),
    ]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("duplicate output path");
    expect(await Bun.file(join(out, "same.generated.ts")).exists()).toBe(false);
  });
});

describe("systemoneprompts eval", () => {
  let calls = 0;
  const server = Bun.serve({
    port: 0,
    async fetch(req) {
      calls += 1;
      const body = (await req.json()) as {
        state: { ticket?: { message?: string } };
        questions: Record<string, { type: string }>;
      };
      if (body.state.ticket?.message === "fail") {
        return new Response("mock failure", { status: 400 });
      }
      const answers = Object.fromEntries(
        Object.entries(body.questions).map(([id, question]) => [
          id,
          question.type === "noul"
            ? { type: "noul", noul: 0.9 }
            : question.type === "choice"
              ? { type: "choice", choice: "billing", confidence: 0.8, probabilities: {} }
              : body.state.ticket?.message === "factor-fail"
                ? { type: "score", confidence: 0.7, legend: {}, probabilities: {} }
                : {
                    type: "score",
                    score: 1.7,
                    confidence: body.state.ticket?.message === "sweep" ? 0.6 : 0.7,
                    legend: {},
                    probabilities: {},
                  },
        ]),
      );
      return Response.json({
        model: "jev-test",
        answers,
        usage: { input_tokens: 1, output_tokens: 1 },
      });
    },
  });
  afterAll(() => server.stop(true));

  const env = { TYPESAFE_API_KEY: "test", TYPESAFE_BASE_URL: `http://localhost:${server.port}` };
  const state = {
    ticket: { message: "ok", sender: { email: "a@b.c", display_name: "A" } },
    customer: { open_orders: [] },
    policy: { sensitive_credentials: [] },
  };

  test("rejects malformed cases before any API call", async () => {
    calls = 0;
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-eval-"));
    const cases = join(dir, "cases.jsonl");
    await writeFile(
      cases,
      `${JSON.stringify({ id: 42, state: 3, labels: { missing: true }, factors: { "topic.billing": "yes" } })}\n`,
    );

    const result = cli(["eval", fixturePath("golden/triage.toml"), "--cases", cases], { env });
    expect(result.exitCode).toBe(1);
    expect(calls).toBe(0);
    expect(result.stderr).toContain("invalid eval case");
    expect(result.stderr).toContain("unknown question id");
    expect(result.stderr).toContain("expected a boolean");
  });

  test("rejects invalid sweeps before any API call", async () => {
    calls = 0;
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-eval-"));
    const cases = join(dir, "cases.jsonl");
    await writeFile(cases, `${JSON.stringify({ state })}\n`);

    const result = cli(
      ["eval", fixturePath("golden/triage.toml"), "--cases", cases, "--sweep", "missing"],
      { env },
    );
    expect(result.exitCode).toBe(1);
    expect(calls).toBe(0);
    expect(result.stderr).toContain("unknown factor `missing`");
  });

  test("rejects a report path that resolves to an input before any API call or write", async () => {
    calls = 0;
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-eval-"));
    const cases = join(dir, "cases.jsonl");
    await writeFile(cases, `${JSON.stringify({ state })}\n`);
    const original = await readFile(cases, "utf8");
    const report = `${dir}/nested/../cases.jsonl`;

    const result = cli(
      ["eval", fixturePath("golden/triage.toml"), "--cases", cases, "--report", report],
      { env },
    );
    expect(result.exitCode).toBe(1);
    expect(calls).toBe(0);
    expect(result.stderr).toContain("must not overwrite the definition or cases input");
    expect(await readFile(cases, "utf8")).toBe(original);

    const definition = fixturePath("golden/triage.toml");
    const definitionOriginal = await readFile(definition, "utf8");
    const definitionResult = cli(["eval", definition, "--cases", cases, "--report", definition], {
      env,
    });
    expect(definitionResult.exitCode).toBe(1);
    expect(calls).toBe(0);
    expect(await readFile(definition, "utf8")).toBe(definitionOriginal);
  });

  test("rejects a sweep with no usable truth samples before any API call", async () => {
    calls = 0;
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-eval-"));
    const cases = join(dir, "cases.jsonl");
    await writeFile(cases, `${JSON.stringify({ state })}\n`);

    const result = cli(
      [
        "eval",
        fixturePath("golden/triage.toml"),
        "--cases",
        cases,
        "--sweep",
        "customer.high_frustration",
      ],
      { env },
    );
    expect(result.exitCode).toBe(1);
    expect(calls).toBe(0);
    expect(result.stderr).toContain("no usable truth samples");
  });

  test("retains a partial report for execution errors", async () => {
    calls = 0;
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-eval-"));
    const cases = join(dir, "cases.jsonl");
    const report = join(dir, "report.json");
    await writeFile(report, "stale report\n");
    await writeFile(
      cases,
      `${JSON.stringify({ id: "ok", state, labels: { topic: "billing" } })}\n${JSON.stringify({
        id: "bad-api",
        state: { ...state, ticket: { ...state.ticket, message: "fail" } },
        labels: { topic: "billing" },
      })}\n`,
    );

    const result = cli(
      ["eval", fixturePath("golden/triage.toml"), "--cases", cases, "--report", report],
      { env },
    );
    expect(result.exitCode).toBe(1);
    expect(calls).toBe(2);
    const output = JSON.parse(await readFile(report, "utf8")) as {
      cases: number;
      errors: number;
      questions: Record<
        string,
        {
          accuracy: number;
          correct: number;
          total: number;
          confusion: Record<string, Record<string, number>>;
        }
      >;
    };
    expect(output.cases).toBe(2);
    expect(output.errors).toBe(1);
    expect(output.questions.topic).toEqual({
      accuracy: 1,
      correct: 1,
      total: 1,
      confusion: { billing: { billing: 1 } },
    });
  });

  test("retains question metrics when factor evaluation fails", async () => {
    calls = 0;
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-eval-"));
    const cases = join(dir, "cases.jsonl");
    const report = join(dir, "report.json");
    await writeFile(
      cases,
      `${JSON.stringify({
        id: "factor-fail",
        state: { ...state, ticket: { ...state.ticket, message: "factor-fail" } },
        labels: { topic: "billing" },
      })}\n`,
    );

    const result = cli(
      ["eval", fixturePath("golden/triage.toml"), "--cases", cases, "--report", report],
      { env },
    );
    expect(result.exitCode).toBe(1);
    expect(calls).toBe(1);
    expect(result.stderr).toContain("factor evaluation failed");
    const output = JSON.parse(await readFile(report, "utf8")) as {
      errors: number;
      questions: Record<
        string,
        {
          accuracy: number;
          correct: number;
          total: number;
          confusion: Record<string, Record<string, number>>;
        }
      >;
    };
    expect(output.errors).toBe(1);
    expect(output.questions.topic).toEqual({
      accuracy: 1,
      correct: 1,
      total: 1,
      confusion: { billing: { billing: 1 } },
    });
  });

  test("sweeps the first numeric field while retaining other comparators", async () => {
    calls = 0;
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-eval-"));
    const cases = join(dir, "cases.jsonl");
    const report = join(dir, "report.json");
    await writeFile(
      cases,
      `${JSON.stringify({
        state: { ...state, ticket: { ...state.ticket, message: "sweep" } },
        factors: { "customer.high_frustration": false },
      })}\n`,
    );

    const result = cli(
      [
        "eval",
        fixturePath("golden/triage.toml"),
        "--cases",
        cases,
        "--sweep",
        "customer.high_frustration",
        "--report",
        report,
      ],
      { env },
    );
    expect(result.exitCode).toBe(0);
    const output = JSON.parse(await readFile(report, "utf8")) as {
      sweep: { field: string; rows: Array<{ accuracy: number }> };
    };
    expect(output.sweep.field).toBe("score");
    expect(output.sweep.rows[0]?.accuracy).toBe(1);
  });
});

describe("systemoneprompts run", () => {
  const requests: unknown[] = [];
  const server = Bun.serve({
    port: 0,
    async fetch(req) {
      const body = (await req.json()) as { questions: Record<string, { type: string }> };
      requests.push(body);
      const answers = Object.fromEntries(
        Object.entries(body.questions).map(([id, q]) => [
          id,
          q.type === "noul"
            ? { type: "noul", noul: 0.9 }
            : q.type === "choice"
              ? {
                  type: "choice",
                  choice: "billing",
                  confidence: 0.8,
                  probabilities: { billing: 0.8 },
                }
              : { type: "score", score: 1.7, confidence: 0.7, legend: {}, probabilities: {} },
        ]),
      );
      return Response.json({
        model: "jev-test",
        answers,
        usage: { input_tokens: 5, output_tokens: 1 },
      });
    },
  });
  afterAll(() => server.stop(true));

  const env = { TYPESAFE_API_KEY: "test", TYPESAFE_BASE_URL: `http://localhost:${server.port}` };

  test("reads state from --state, prints answers and factors, --json is machine readable", async () => {
    const dir = await mkdtemp(join(tmpdir(), "jev-cli-"));
    const state = join(dir, "state.json");
    await writeFile(
      state,
      JSON.stringify({
        ticket: { message: "Charged twice", sender: { email: "a@b.c", display_name: "A" } },
        customer: { open_orders: [] },
        policy: { sensitive_credentials: [] },
      }),
    );
    const result = cli(
      [
        "run",
        fixturePath("golden/triage.toml"),
        "--state",
        state,
        "--json",
        "--model",
        "jev-pinned",
      ],
      { env },
    );
    expect(result.stderr).toBe("");
    expect(result.exitCode).toBe(0);
    const out = JSON.parse(result.stdout) as { factors: Record<string, boolean>; model: string };
    expect(out.model).toBe("jev-test");
    expect(out.factors).toEqual({
      "topic.billing": true,
      "topic.billing.confident": true,
      "customer.high_frustration": true,
      "spam.gray_band": false,
    });
    expect((requests.at(-1) as { model: string }).model).toBe("jev-pinned");
  });

  test("a state that violates [requires] fails before any network call", async () => {
    const before = requests.length;
    const result = cli(["run", fixturePath("golden/triage.toml")], {
      env,
      input: JSON.stringify({ ticket: { message: 42 } }),
    });
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("ticket.message: expected string, got number");
    expect(requests.length).toBe(before);
  });

  test("malformed state JSON names the source", () => {
    const result = cli(["run", fixturePath("golden/triage.toml")], { env, input: "{ nope" });
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("<stdin>:");
  });
});
