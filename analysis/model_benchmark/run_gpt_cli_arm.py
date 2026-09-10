#!/usr/bin/env python3
"""Run the blind GPT subscription arm. Reads gpt_inputs.json, never the key.

Requires a current Codex CLI logged in using ChatGPT. Standard library only.
One fresh, tool-free conversation per attempt; no scoring or correctness feedback.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from gpt_transport import (CONDITIONS, DEFAULT_MODELS, HARNESS_VERSION, call,
                           catalog_path, classify_strategy, cli_path, clean_env,
                           digest, isolated_catalog, parse_answer)
from gpt_wire_audit import PROMPT, SYSTEM, audit

HERE = Path(__file__).resolve().parent
RUNS = HERE / "output" / "gpt_cli_arm_runs.jsonl"


def load_inputs(path: Path) -> tuple[dict, str]:
    raw = path.read_text()
    payload = json.loads(raw)
    if set(payload) != {"schema_version", "system", "items"} or payload["schema_version"] != 1:
        raise ValueError("Unexpected input schema; only the prompt-only export is allowed")
    ids = []
    for row in payload["items"]:
        if set(row) != {"instance_id", "is_practice", "n", "prompt", "control_prompt"}:
            raise ValueError("Unexpected input fields; possible answer-key contamination")
        if not isinstance(row["prompt"], str) or not isinstance(row["control_prompt"], str):
            raise ValueError("Invalid prompt types")
        if row["n"] != 4 or type(row["is_practice"]) is not bool:
            raise ValueError("Expected the original 4x4 item set")
        if not row["is_practice"]:
            ids.append(row["instance_id"])
    if len(ids) != 6 or len(set(ids)) != 6:
        raise ValueError("Expected six distinct canonical items")
    return payload, digest(raw)


def key(row: dict) -> str:
    return "|".join(str(row[k]) for k in ("model_alias", "condition", "instance_id", "replicate"))


def load_done(path: Path, manifest_id: str) -> set[str]:
    done = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("manifest_id") != manifest_id:
                raise ValueError("Results belong to a different manifest; use a new --out path")
            if not row.get("error"):
                if key(row) in done:
                    raise ValueError("Duplicate successful session in results")
                done.add(key(row))
    return done


def preflight(models: list[str], catalog: dict) -> dict:
    result = {"wire_audits": [], "subscription_probes": []}
    for model in models:
        for effort in ("none", "low", "high"):
            result["wire_audits"].append(audit(model, effort, catalog))
            probe = call(model, effort, PROMPT, SYSTEM, catalog)
            if probe["text"].strip() != "READY":
                raise ValueError(f"Unexpected readiness response from {model}/{effort}")
            result["subscription_probes"].append({"model": model, "effort": effort,
                                                  **probe})
            print(f"Preflight {model}/{effort}: zero tools; subscription accepted; "
                  f"{probe['usage']['reasoning_output_tokens']} reasoning tokens", flush=True)
    return result


def session(spec: dict, inputs: dict, catalog: dict, manifest_id: str) -> dict:
    item = next(i for i in inputs["items"] if i["instance_id"] == spec["instance_id"])
    effort = CONDITIONS[spec["condition"]]
    clues = spec["condition"] != "control_no_clues"
    prompt = item["prompt" if clues else "control_prompt"]
    row = {
        "arm": "gpt_cli_subscription_blind", "harness_version": HARNESS_VERSION,
        "manifest_id": manifest_id, **spec, "model_reported": None,
        "model_verification": "configured model; outgoing request audited locally; server model ID not exposed by CLI",
        "effort": effort, "clues_shown": clues, "is_practice": item["is_practice"],
        "prompt_sha256": digest(prompt), "system_sha256": digest(inputs["system"]),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "submitted": None, "parse_failed": None, "output_tokens": None,
        "thinking_tokens": None, "input_tokens": None, "cached_input_tokens": None,
        "aux_output_tokens": 0, "api_ms": None, "wall_ms": None,
        "num_turns": None, "tool_events": None, "strategy": None,
        "text": None, "error": None,
    }
    try:
        result = call(spec["model_alias"], effort, prompt, inputs["system"], catalog)
        usage = result["usage"]
        row.update(result)
        submitted = parse_answer(result["text"])
        row.update(submitted=submitted, parse_failed=submitted is None,
                   output_tokens=usage["output_tokens"],
                   thinking_tokens=usage["reasoning_output_tokens"],
                   input_tokens=usage["input_tokens"],
                   cached_input_tokens=usage["cached_input_tokens"],
                   strategy=classify_strategy(result["text"]))
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--replicates", type=int, default=5)
    ap.add_argument("--workers", type=int, default=1,
                    help="Concurrent independent CLI processes; recorded in manifest")
    ap.add_argument("--inputs", type=Path, default=HERE / "gpt_inputs.json")
    ap.add_argument("--out", type=Path, default=RUNS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preflight-only", action="store_true")
    args = ap.parse_args()
    if args.replicates < 1 or not 1 <= args.workers <= 3:
        ap.error("replicates must be positive; workers must be 1..3")
    if len(set(args.models)) != len(args.models):
        ap.error("duplicate models")
    inputs, inputs_hash = load_inputs(args.inputs)
    catalog = isolated_catalog(json.loads(catalog_path().read_text()), args.models)
    plan = [{"model_alias": m, "condition": c, "instance_id": i["instance_id"], "replicate": r}
            for r in range(1, args.replicates + 1)
            for c in CONDITIONS for i in inputs["items"] if not i["is_practice"]
            for m in args.models]
    print(f"{len(plan)} sessions: {len(args.models)} models x 4 conditions x 6 items "
          f"x {args.replicates} replicates; {args.workers} worker(s)", flush=True)
    print("ChatGPT subscription only. One attempt each; mandatory no-clues controls.", flush=True)
    if args.dry_run:
        print("Models:", ", ".join(args.models))
        print("No inference. Next run performs wire audits and subscription probes first.")
        return 0
    status = subprocess.run([cli_path(), "login", "status"], capture_output=True,
                            text=True, env=clean_env(), timeout=20)
    if status.returncode or "Logged in using ChatGPT" not in status.stdout + status.stderr:
        raise RuntimeError("ChatGPT login required. API-key billing is prohibited for this arm.")
    version = subprocess.check_output([cli_path(), "--version"], text=True).strip()
    code_hashes = {name: digest((HERE / name).read_text()) for name in
                   ("gpt_transport.py", "gpt_wire_audit.py", "run_gpt_cli_arm.py")}
    identity = {"harness_version": HARNESS_VERSION, "cli_version": version,
                "inputs_sha256": inputs_hash, "models": args.models,
                "catalog_sha256": digest(json.dumps(catalog, sort_keys=True)),
                "replicates": args.replicates, "workers": args.workers,
                "source_sha256": code_hashes, "plan": plan}
    manifest_id = digest(json.dumps(identity, sort_keys=True))
    manifest_path = args.out.with_suffix(".manifest.json")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["manifest_id"] != manifest_id:
            raise ValueError("Configuration/code/input changed. Use a new --out path.")
    else:
        if args.out.exists() and args.out.stat().st_size:
            raise ValueError("Existing results have no manifest; refusing to append")
        manifest = {**identity, "manifest_id": manifest_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "authentication": "chatgpt", "preflight": preflight(args.models, catalog)}
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if args.preflight_only:
        print(f"Preflight passed -> {manifest_path}")
        return 0
    done = load_done(args.out, manifest_id)
    todo = [s for s in plan if key(s) not in done]
    print(f"{len(done)} already complete; {len(todo)} remaining", flush=True)
    started = time.perf_counter()
    errors = 0
    # Bound in-flight work. Stop scheduling on the first failure; retain all
    # already-started rows so a resume cannot silently duplicate completed work.
    with args.out.open("a") as out, concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        iterator = iter(todo)
        pending = {}
        def submit_next():
            spec = next(iterator, None)
            if spec is not None:
                pending[pool.submit(session, spec, inputs, catalog, manifest_id)] = spec
        for _ in range(args.workers):
            submit_next()
        count = 0
        while pending:
            ready, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in ready:
                pending.pop(future)
                row = future.result()
                out.write(json.dumps(row) + "\n")
                out.flush()
                count += 1
                errors += bool(row["error"])
                print(f"[{count}/{len(todo)}] {'ERROR' if row['error'] else 'saved'} "
                      f"{key(row)} out={row['output_tokens']} thinking={row['thinking_tokens']} "
                      + (row["error"][:300] if row["error"] else f"wall={row['wall_ms']/1000:.2f}s"), flush=True)
            if not errors:
                for _ in ready:
                    submit_next()
    print(f"Saved to {args.out}; {(time.perf_counter()-started)/60:.1f} minutes", flush=True)
    if errors:
        print("Stopped after failure. Resolve the error and rerun to resume.")
        return 1
    print("Collection complete. Grade separately with: python3 grade_gpt_runs.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        sys.exit(1)
