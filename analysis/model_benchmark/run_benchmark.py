#!/usr/bin/env python3
"""Model benchmark for Project Touchstone — Claim D.

Runs Claude Haiku 4.5, Sonnet 5 and Opus 5 against the *same six band-2 items*
the human participants solved, under three reasoning conditions, and records
tokens, wall-clock latency, attempts and correctness for every attempt.

One "session" here = one (model, condition, instance, replicate). Inside a
session the model gets up to three attempts, exactly as a human did, with the
app's own wrong-answer text fed back as the next user turn. Attempt 2 and 3
resend the whole conversation, so their input tokens grow the way a real
multi-attempt attacker's would.

Results append to output/runs.jsonl. Re-running skips sessions already present,
so an interrupted run resumes without re-spending.

    export ANTHROPIC_API_KEY=sk-ant-...
    python run_benchmark.py --dry-run          # plan + cost estimate, no calls
    python run_benchmark.py                    # the full 3x3x6x5 grid
    python run_benchmark.py --models claude-haiku-4-5 --replicates 1
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic

from items import MAX_ATTEMPTS, Item, load_items, verify
from prompts import CONDITIONS, item_prompt, retry_prompt, system_prompt

OUT_DIR = Path(__file__).resolve().parent / "output"
RUNS_PATH = OUT_DIR / "runs.jsonl"

# Anthropic first-party API rates, USD per million tokens. Thinking tokens are
# billed as output tokens, so no separate line is needed.
PRICING = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
}
DEFAULT_MODELS = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]

# Rough per-attempt token expectations, used only by --dry-run to quote a cost
# before any money is spent. Not used in analysis.
ESTIMATE = {
    "answer_only": (240, 12),
    "visible_reasoning": (240, 600),
    "extended_thinking": (240, 1400),
}

ANSWER_RE = re.compile(r"ANSWER\s*:\s*\**\s*([A-Ga-g])\s*([1-7])", re.IGNORECASE)
BOX_RE = re.compile(r"\b([A-Ga-g])\s?([1-7])\b")


def thinking_param(model: str, mode: str) -> dict | None:
    """Per-model thinking config. The API surface differs by model generation."""
    if mode == "off":
        # Haiku 4.5 has no disabled-thinking object: omitting the parameter is
        # how you turn it off. Sonnet 5 and Opus 5 take an explicit disable
        # (accepted on Opus 5 at effort high or lower; we leave effort default).
        return None if model == "claude-haiku-4-5" else {"type": "disabled"}
    if model == "claude-haiku-4-5":
        # budget_tokens is still the only thinking config on Haiku 4.5. It must
        # be below max_tokens and at least 1024.
        return {"type": "enabled", "budget_tokens": 8000}
    return {"type": "adaptive"}


def parse_answer(text: str) -> str | None:
    """Extract the submitted box. Mirrors what the two radio groups captured."""
    matches = ANSWER_RE.findall(text)
    if not matches:
        matches = BOX_RE.findall(text)
    if not matches:
        return None
    col, row = matches[-1]
    return f"{col.upper()}{row}"


@dataclass
class Attempt:
    attempt: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    stop_reason: str | None
    submitted: str | None
    correct: bool
    parse_failed: bool
    response_chars: int
    thinking_chars: int
    api_retries: int
    text: str


@dataclass
class Session:
    model: str
    condition: str
    instance_id: str
    replicate: int
    is_practice: bool
    solution: str
    solved: bool = False
    attempts_used: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None
    attempts: list[dict] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.model}|{self.condition}|{self.instance_id}|{self.replicate}"


def call_with_retry(client, params: dict, *, max_retries: int = 6):
    """Own retry loop so `latency_ms` never includes backoff sleep.

    The SDK's built-in retries would fold rate-limit waits into the timed call
    and inflate the latency figure this benchmark exists to report.
    """
    retries = 0
    while True:
        started = time.perf_counter()
        try:
            response = client.messages.create(**params)
            return response, (time.perf_counter() - started) * 1000.0, retries
        except (anthropic.RateLimitError, anthropic.APITimeoutError,
                anthropic.APIConnectionError, anthropic.InternalServerError) as exc:
            if retries >= max_retries:
                raise
            sleep = min(60.0, 2.0 ** retries) + random.uniform(0, 1.0)
            print(
                f"    {type(exc).__name__}, retry {retries + 1}/{max_retries} "
                f"in {sleep:.1f}s",
                file=sys.stderr,
            )
            time.sleep(sleep)
            retries += 1


def run_session(client, model: str, condition: str, item: Item, replicate: int,
                position: int, of: int) -> Session:
    cfg = CONDITIONS[condition]
    session = Session(
        model=model,
        condition=condition,
        instance_id=item.instance_id,
        replicate=replicate,
        is_practice=item.is_practice,
        solution=item.solution,
    )

    messages: list[dict] = [
        {"role": "user", "content": item_prompt(item, position, of)}
    ]
    thinking = thinking_param(model, cfg["thinking"])

    for attempt_no in range(1, MAX_ATTEMPTS + 1):
        params = {
            "model": model,
            "max_tokens": cfg["max_tokens"],
            "system": system_prompt(condition),
            "messages": messages,
        }
        if thinking is not None:
            params["thinking"] = thinking

        try:
            response, latency_ms, retries = call_with_retry(client, params)
        except Exception as exc:  # recorded, never silently dropped
            session.error = f"{type(exc).__name__}: {exc}"
            break

        text = "".join(b.text for b in response.content if b.type == "text")
        thinking_chars = sum(
            len(getattr(b, "thinking", "") or "")
            for b in response.content
            if b.type == "thinking"
        )
        submitted = parse_answer(text)
        correct = submitted == item.solution

        usage = response.usage
        attempt = Attempt(
            attempt=attempt_no,
            latency_ms=latency_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=(
                getattr(usage, "cache_creation_input_tokens", 0) or 0
            ),
            stop_reason=response.stop_reason,
            submitted=submitted,
            correct=correct,
            parse_failed=submitted is None,
            response_chars=len(text),
            thinking_chars=thinking_chars,
            api_retries=retries,
            text=text,
        )
        session.attempts.append(asdict(attempt))
        session.attempts_used = attempt_no
        session.total_input_tokens += attempt.input_tokens
        session.total_output_tokens += attempt.output_tokens
        session.total_latency_ms += latency_ms

        if correct:
            session.solved = True
            break
        # Wrong: replay the app's own dialog text as the next user turn.
        messages = messages + [
            {"role": "assistant", "content": text or "(no answer)"},
            {"role": "user", "content": retry_prompt(attempt_no)},
        ]

    rates = PRICING[model]
    session.cost_usd = (
        session.total_input_tokens / 1e6 * rates["input"]
        + session.total_output_tokens / 1e6 * rates["output"]
    )
    return session


def load_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("error"):
            continue  # let a previously failed session be retried
        done.add(
            f"{row['model']}|{row['condition']}|{row['instance_id']}|{row['replicate']}"
        )
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--conditions", nargs="+", default=list(CONDITIONS))
    ap.add_argument("--replicates", type=int, default=5)
    ap.add_argument("--include-practice", action="store_true",
                    help="also run PRAC01, as humans did before the six")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=RUNS_PATH)
    args = ap.parse_args()

    practice, canonical = load_items()
    problems = verify([practice, *canonical])
    if problems:
        print("Item verification failed:", *problems, sep="\n  ")
        return 1

    items = ([practice] if args.include_practice else []) + canonical
    plan = [
        (m, c, it, r)
        for m in args.models
        for c in args.conditions
        for it in items
        for r in range(1, args.replicates + 1)
    ]

    unknown = [m for m in args.models if m not in PRICING]
    if unknown:
        print(f"No pricing for: {', '.join(unknown)}")
        return 1

    if args.dry_run:
        print(f"{len(plan)} sessions planned "
              f"({len(args.models)} models x {len(args.conditions)} conditions "
              f"x {len(items)} items x {args.replicates} replicates)\n")
        print("Cost estimate assumes 1.3 attempts/session at nominal token counts:")
        total = 0.0
        for model in args.models:
            for cond in args.conditions:
                tin, tout = ESTIMATE[cond]
                n = len(items) * args.replicates
                rates = PRICING[model]
                usd = 1.3 * n * (tin / 1e6 * rates["input"]
                                 + tout / 1e6 * rates["output"])
                total += usd
                print(f"  {model:<22} {cond:<20} {n:>4} sessions  ${usd:0.4f}")
        print(f"\n  {'TOTAL':<43} ${total:0.4f}")
        print("\nItems (verbatim, as the human cohort received them):")
        for k, it in enumerate(items, start=1):
            print(f"  {k}. {it.instance_id} -> {it.solution}")
        return 0

    if not (os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or (Path.home() / ".config" / "anthropic").exists()):
        print("No Anthropic credentials found. Set ANTHROPIC_API_KEY, or run "
              "`ant auth login`.", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(args.out)
    if done:
        print(f"Resuming: {len(done)} sessions already recorded.")

    # max_retries=0: retries are handled in call_with_retry so they stay out of
    # the latency measurement.
    client = anthropic.Anthropic(max_retries=0, timeout=600.0)

    started = time.time()
    ran = 0
    with args.out.open("a") as fh:
        for model, condition, item, replicate in plan:
            key = f"{model}|{condition}|{item.instance_id}|{replicate}"
            if key in done:
                continue
            position = 0 if item.is_practice else canonical.index(item) + 1
            session = run_session(client, model, condition, item, replicate,
                                  position, len(canonical))
            fh.write(json.dumps(asdict(session)) + "\n")
            fh.flush()
            ran += 1
            flag = "OK " if session.solved else ("ERR" if session.error else "MISS")
            print(f"[{ran}/{len(plan) - len(done)}] {flag} {model:<20} "
                  f"{condition:<18} {item.instance_id} r{replicate}  "
                  f"{session.attempts_used} att  "
                  f"{session.total_output_tokens:>6} out  "
                  f"{session.total_latency_ms / 1000:>6.1f}s  "
                  f"${session.cost_usd:0.5f}"
                  + (f"  {session.error}" if session.error else ""))

    print(f"\n{ran} sessions in {(time.time() - started) / 60:0.1f} min "
          f"-> {args.out}")
    print("Next: python analyze_benchmark.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
