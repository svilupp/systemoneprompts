#!/usr/bin/env python3
"""Prove native image cache records and both read directions match, without network."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "packages/typescript"
PY = ROOT / "packages/python"

TS_WORKER = r'''
const [root, fixtureFile, directory, action] = process.argv.slice(2);
const { readFile } = await import("node:fs/promises");
const { createCachingFetch } = await import(root + "/packages/typescript/src/dev/cache.ts");
const cases = JSON.parse(await readFile(fixtureFile, "utf8"));
let calls = 0;
const cache = createCachingFetch({dir: directory, mode: action === "write" ? "read-write" : "read-only", fetch: async (url, init) => {
  calls++;
  if (action !== "write") throw new Error("read-only called network");
  const request = JSON.parse(init.body);
  return Response.json({model:"jev-1.14.0", answers:{target_present:{type:"noul",noul:0.99}, target_box:{type:"box",box:{top:0.25,bottom:0.75,left:0.25,right:0.75},confidence:request.state.null_confidence?null:0.9}},usage:{input_tokens:4,output_tokens:2}});
}});
for (const item of cases) {
  const response = await cache(item.endpoint, {method:"POST", headers:{"TypeSafe-Danger-Zone-Images":"true"},body:JSON.stringify(item.request)});
  const value = await response.json();
  if (value.answers.target_box.box.top !== 0.25 || value.answers.target_box.confidence !== (item.request.state.null_confidence?null:0.9)) throw new Error("wrong cached answer");
  if (action === "read" && (value.usage.input_tokens || value.usage.output_tokens)) throw new Error("cache hit spent tokens");
}
console.log(JSON.stringify({calls,stats:cache.stats()}));
'''

PY_WORKER = r'''
import json, sys
from dataclasses import asdict
from systemoneprompts.cache import FetchResponse, create_caching_fetch
root, fixture_file, directory, action = sys.argv[1:]
cases = json.load(open(fixture_file))
calls = 0
def fetch(url, init):
    global calls
    calls += 1
    assert action == "write", "read-only called network"
    request = json.loads(init["body"])
    result = {"model":"jev-1.14.0", "answers":{"target_present":{"type":"noul","noul":0.99}, "target_box":{"type":"box","box":{"top":0.25,"bottom":0.75,"left":0.25,"right":0.75},"confidence":None if request["state"].get("null_confidence") else 0.9}},"usage":{"input_tokens":4,"output_tokens":2}}
    return FetchResponse(status=200, body=json.dumps(result).encode())
cache = create_caching_fetch(dir=directory, mode="read-write" if action == "write" else "read-only", fetch=fetch)
for item in cases:
    value = cache(item["endpoint"], {"method":"POST", "headers":{"TypeSafe-Danger-Zone-Images":"true"}, "body":json.dumps(item["request"])}).json()
    assert value["answers"]["target_box"]["box"]["top"] == 0.25
    assert value["answers"]["target_box"]["confidence"] == (None if item["request"]["state"].get("null_confidence") else 0.9)
    if action == "read": assert value["usage"] == {"input_tokens":0,"output_tokens":0}
print(json.dumps({"calls":calls,"stats":asdict(cache.stats())}))
'''


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="image-cache-parity-") as temporary:
        work = Path(temporary)
        fixture = json.loads((ROOT / "conformance/v1/providers/native-images.json").read_text())
        request = {"model": fixture["model"], "state": {"photo": "<asset:photo>", "unicode": "é 雪", "nested": {"b": 2, "a": 1}}, "questions": fixture["questions"]}
        cases = []
        for index in range(5):
            current = json.loads(json.dumps(request))
            fmt = "jpg" if index == 1 else "png"
            data = (ROOT / f"conformance/v1/images/rectangle.{fmt}").read_bytes()
            current["assets"] = {"photo": {"type": "image", "format": fmt, "data_base64": base64.b64encode(data).decode()}}
            if index == 2:
                current["questions"]["target_box"]["instructions"] += " Find the complete rectangle."
            if index == 4:
                current["state"]["null_confidence"] = True
            endpoint = "https://native.example/v1/systemone" if index == 3 else "https://api.typesafe.ai/v1/systemone"
            cases.append({"endpoint": endpoint, "request": current})
        fixture_file = work / "cases.json"
        fixture_file.write_text(json.dumps(cases))
        scripts = {"ts": work / "worker.ts", "py": work / "worker.py"}
        scripts["ts"].write_text(TS_WORKER)
        scripts["py"].write_text(PY_WORKER)

        def run(language: str, directory: Path, action: str) -> None:
            command = ["bun", str(scripts[language])] if language == "ts" else [str(PY / ".venv/bin/python"), str(scripts[language])]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(PY / "src")
            result = subprocess.run([*command, str(ROOT), str(fixture_file), str(directory), action], text=True, capture_output=True, env=env, check=True)
            value = json.loads(result.stdout)
            assert value["calls"] == (len(cases) if action == "write" else 0), value
            assert value["stats"]["hits"] == (0 if action == "write" else len(cases) * 2), value

        ts_records, py_records = work / "ts", work / "py"
        run("ts", ts_records, "write")
        run("py", ts_records, "read")
        run("py", py_records, "write")
        run("ts", py_records, "read")
        a = {str(path.relative_to(ts_records)): path.read_bytes() for path in ts_records.rglob("*.json")}
        b = {str(path.relative_to(py_records)): path.read_bytes() for path in py_records.rglob("*.json")}
        assert len(a) == len(cases)
        assert a == b, "cross-language image cache paths, hashes, or record bytes differ"
    print("Image cache parity: five variants, both read directions, paths/hashes/record bytes match")


if __name__ == "__main__":
    main()
