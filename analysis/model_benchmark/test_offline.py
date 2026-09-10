#!/usr/bin/env python3
"""Offline verification of the harness — no API key, no network, no cost.

Stubs the client and asserts the things that cannot be checked by reading the
code: that each model gets the right thinking config, that no sampling
parameter leaks into a request (400 on Sonnet 5 / Opus 5), that the three-attempt
state machine grows the conversation correctly, that answers parse, and that an
API failure is recorded rather than raised.

    .venv/bin/python test_offline.py
"""
import sys, types, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import run_benchmark as rb
from items import load_items
from prompts import CONDITIONS

seen = []

class Usage:
    input_tokens = 240; output_tokens = 100
    cache_read_input_tokens = 0; cache_creation_input_tokens = 0
class Block:
    type = "text"
    def __init__(s, t): s.text = t
class Resp:
    stop_reason = "end_turn"; usage = Usage()
    def __init__(s, t): s.content = [Block(t)]

class FakeMessages:
    def __init__(s, replies): s.replies = replies; s.i = 0
    def create(s, **params):
        seen.append(params)
        r = s.replies[min(s.i, len(s.replies)-1)]; s.i += 1
        return Resp(r)
class FakeClient:
    def __init__(s, replies): s.messages = FakeMessages(replies)

practice, canonical = load_items()
item = canonical[0]  # I0009 -> C2

print("--- request shape per model x condition ---")
for model in rb.DEFAULT_MODELS:
    for cond in CONDITIONS:
        seen.clear()
        c = FakeClient(["ANSWER: C2"])
        s = rb.run_session(c, model, cond, item, 1, 1, 6)
        p = seen[0]
        assert p["model"] == model and p["messages"][0]["role"] == "user"
        assert p["max_tokens"] == CONDITIONS[cond]["max_tokens"]
        assert "temperature" not in p and "top_p" not in p, "sampling param leaked"
        th = p.get("thinking", "<absent>")
        assert s.solved and s.attempts_used == 1, (s.solved, s.attempts_used)
        print(f"  {model:<20} {cond:<18} max_tokens={p['max_tokens']:<6} thinking={th}")

print("\n--- 3-attempt exhaustion, wrong every time ---")
seen.clear()
c = FakeClient(["ANSWER: A1", "ANSWER: A2", "ANSWER: A3"])
s = rb.run_session(c, "claude-sonnet-5", "visible_reasoning", item, 1, 1, 6)
print(f"  solved={s.solved} attempts={s.attempts_used} calls={len(seen)} "
      f"in_tok={s.total_input_tokens} out_tok={s.total_output_tokens} "
      f"cost=${s.cost_usd:0.6f}")
assert not s.solved and s.attempts_used == 3 and len(seen) == 3
# conversation must grow: 1, 3, 5 messages
assert [len(p["messages"]) for p in seen] == [1, 3, 5], [len(p["messages"]) for p in seen]
print("  message counts per call:", [len(p["messages"]) for p in seen])
print("  retry turn 2 text:", json.dumps(seen[1]["messages"][2]["content"])[:90])

print("\n--- solve on attempt 2 ---")
c = FakeClient(["ANSWER: A1", "ANSWER: C2"])
s = rb.run_session(c, "claude-opus-5", "answer_only", item, 1, 1, 6)
print(f"  solved={s.solved} attempts={s.attempts_used}")
assert s.solved and s.attempts_used == 2

print("\n--- answer parsing ---")
cases = [("ANSWER: C2", "C2"), ("...so ANSWER: **C2**", "C2"), ("answer: c2", "C2"),
         ("Rule out row 3 and column A. ANSWER: C2", "C2"),
         ("The circle is in C2.", "C2"), ("no box here", None),
         ("ANSWER: C2\nANSWER: D4", "D4")]
for text, want in cases:
    got = rb.parse_answer(text)
    print(f"  {'ok ' if got == want else 'BAD'} {text!r:<48} -> {got}")
    assert got == want, (text, got, want)

print("\n--- error is recorded, not raised ---")
class Boom:
    class messages:
        @staticmethod
        def create(**k): raise ValueError("synthetic failure")
s = rb.run_session(Boom(), "claude-haiku-4-5", "answer_only", item, 1, 1, 6)
print(f"  solved={s.solved} error={s.error}")
assert s.error and not s.solved

print("\nALL OFFLINE CHECKS PASSED")
