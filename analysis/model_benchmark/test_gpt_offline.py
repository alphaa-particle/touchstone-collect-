#!/usr/bin/env python3
"""Regression tests for leakage, effort labels, parsing, and resume integrity."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gpt_transport as transport
from gpt_wire_audit import PROMPT, SYSTEM, validate_request
from prepare_gpt_inputs import export
from run_gpt_cli_arm import load_done, load_inputs, session


def events(text="ANSWER: B3", thinking=0):
    return [{"type": "thread.started", "thread_id": "synthetic"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
            {"type": "turn.completed", "usage": {"input_tokens": 30,
             "cached_input_tokens": 0, "output_tokens": 8 + thinking,
             "reasoning_output_tokens": thinking}}]


class BlindTests(unittest.TestCase):
    def test_prompt_export_matches_claude_byte_for_byte(self):
        from items import load_items
        from prompts import item_prompt, system_prompt
        from run_cli_arm import strip_clues
        practice, canonical = load_items()
        payload = export()
        self.assertEqual(payload["system"], system_prompt("extended_thinking"))
        for position, (row, item) in enumerate(zip(payload["items"], [practice, *canonical])):
            self.assertEqual(row["prompt"], item_prompt(item, position, 6))
            self.assertEqual(row["control_prompt"], strip_clues(row["prompt"]))
            self.assertEqual(set(row), {"instance_id", "is_practice", "n", "prompt", "control_prompt"})

    def test_answer_field_poisoning_rejected(self):
        for poison in ("solution", "correct", "answer_key", "results", "explanation"):
            data = export()
            data["items"][0][poison] = "SECRET_CANARY"
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "input.json"
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_inputs(path)

    def test_collector_sends_only_one_prompt_and_base_instructions(self):
        payload = export()
        item = payload["items"][1]
        for condition in transport.CONDITIONS:
            spec = {"model_alias": "gpt-test", "condition": condition,
                    "instance_id": item["instance_id"], "replicate": 1}
            result = {**transport.parse_events(events(), transport.CONDITIONS[condition]),
                      "wall_ms": 20, "events": events()}
            with patch("run_gpt_cli_arm.call", return_value=result) as caller:
                row = session(spec, payload, {}, "manifest")
            self.assertIsNone(row["error"])
            expected_prompt = item["control_prompt" if condition == "control_no_clues" else "prompt"]
            self.assertEqual(caller.call_args.args, ("gpt-test", transport.CONDITIONS[condition],
                                                     expected_prompt, payload["system"], {}))
            self.assertNotIn("solution", row)
            self.assertNotIn("correct", row)

    def test_tool_events_and_incomplete_turns_rejected(self):
        for kind in ("command_execution", "mcp_tool_call", "web_search", "file_change",
                     "collab_tool_call", "tool_search", "error", "future_unknown_tool"):
            data = events()
            data.insert(2, {"type": "item.started", "item": {"type": kind}})
            with self.assertRaises(ValueError):
                transport.parse_events(data, "none")
        with self.assertRaises(ValueError):
            transport.parse_events(events()[:-1], "none")
        with self.assertRaises(ValueError):
            transport.parse_events(events() + [{"type": "turn.started"}], "none")

    def test_thinking_off_requires_measured_zero(self):
        with self.assertRaises(ValueError):
            transport.parse_events(events(thinking=1), "none")
        data = events()
        del data[-1]["usage"]["reasoning_output_tokens"]
        with self.assertRaises(ValueError):
            transport.parse_events(data, "none")
        self.assertEqual(transport.parse_events(events(thinking=20), "high")["usage"]["reasoning_output_tokens"], 20)

    def test_wire_rejects_tools_and_extra_context(self):
        valid = {"model": "gpt-test", "reasoning": {"effort": "none"},
                 "input": [{"type": "message", "role": "developer",
                            "content": [{"type": "input_text", "text": SYSTEM}]},
                           {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": PROMPT}]}]}
        validate_request(valid, "gpt-test", "none")
        for mutation in ({"tools": [{"type": "web_search"}]},
                         {"previous_response_id": "old"}, {"model": "other"},
                         {"reasoning": {"effort": "low"}}):
            with self.assertRaises(ValueError):
                validate_request({**valid, **mutation}, "gpt-test", "none")
        data = copy.deepcopy(valid)
        data["input"].insert(0, {"type": "additional_tools", "tools": [{"type": "tool_search"}]})
        with self.assertRaises(ValueError):
            validate_request(data, "gpt-test", "none")
        data = copy.deepcopy(valid)
        data["input"][1]["content"][0]["text"] += " SECRET_CANARY"
        with self.assertRaises(ValueError):
            validate_request(data, "gpt-test", "none")

    def test_resume_retries_errors_rejects_mixing_and_duplicates(self):
        row = {"manifest_id": "test", "model_alias": "gpt-test", "condition": "thinking_off",
               "instance_id": "test", "replicate": 1, "error": None}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runs.jsonl"
            path.write_text(json.dumps({**row, "error": "timeout"}) + "\n" + json.dumps(row) + "\n")
            self.assertEqual(len(load_done(path, "test")), 1)
            with self.assertRaises(ValueError):
                load_done(path, "different")
            path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
            with self.assertRaises(ValueError):
                load_done(path, "test")

    def test_parser_matches_claude(self):
        from run_cli_arm import parse_answer
        for text in ("ANSWER: B3", "answer: **a2**", "The box is D4.",
                     "ANSWER: A1\nANSWER: D4", "no answer"):
            self.assertEqual(transport.parse_answer(text), parse_answer(text))

    def test_catalog_changes_only_tool_exposure(self):
        original = {"slug": "gpt-test", "supported_reasoning_levels": [{"effort": "low"}],
                    "base_instructions": "original", "use_responses_lite": True}
        result = transport.isolated_catalog({"models": [original]}, ["gpt-test"])["models"][0]
        self.assertEqual(result["slug"], original["slug"])
        self.assertEqual(result["supported_reasoning_levels"], original["supported_reasoning_levels"])
        self.assertEqual(result["base_instructions"], original["base_instructions"])
        self.assertEqual(result["shell_type"], "disabled")
        self.assertIsNone(result["apply_patch_tool_type"])
        self.assertNotIn("shell_type", original)

    def test_grader_rejects_incomplete_collection_before_loading_answers(self):
        from grade_gpt_runs import grade
        identity = {"harness_version": transport.HARNESS_VERSION,
                    "models": ["gpt-test"],
                    "plan": [{"model_alias": "gpt-test", "condition": "thinking_off",
                              "instance_id": "synthetic", "replicate": 1}]}
        manifest = {**identity, "manifest_id": transport.digest(json.dumps(identity, sort_keys=True)),
                    "authentication": "chatgpt", "created_at": "synthetic",
                    "preflight": {"wire_audits": [], "subscription_probes": []}}
        for effort in ("none", "low", "high"):
            manifest["preflight"]["wire_audits"].append({"model": "gpt-test", "effort": effort,
                "tools": [], "system_matches": True, "user_matches": True, "no_previous_response": True})
            manifest["preflight"]["subscription_probes"].append({"model": "gpt-test", "effort": effort, "events": events("READY")})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runs.jsonl"
            path.write_text("")
            path.with_suffix(".manifest.json").write_text(json.dumps(manifest))
            with patch("items.load_items", side_effect=AssertionError("answer key read too early")):
                with self.assertRaisesRegex(ValueError, "missing"):
                    grade(path)

    def test_complete_grading_and_control_failure(self):
        from grade_gpt_runs import grade, main as grade_main
        from items import load_items
        _, canonical = load_items()
        answers = {i.instance_id: i.solution for i in canonical}
        inputs = export()
        plan = [{"model_alias": "gpt-test", "condition": c,
                 "instance_id": i.instance_id, "replicate": 1}
                for c in transport.CONDITIONS for i in canonical]
        identity = {"harness_version": transport.HARNESS_VERSION, "models": ["gpt-test"],
                    "plan": plan, "replicates": 1, "workers": 1, "cli_version": "synthetic",
                    "inputs_sha256": transport.digest(json.dumps(inputs, indent=2, ensure_ascii=False) + "\n")}
        manifest = {**identity, "manifest_id": transport.digest(json.dumps(identity, sort_keys=True)),
                    "authentication": "chatgpt", "created_at": "synthetic",
                    "preflight": {"wire_audits": [], "subscription_probes": []}}
        for effort in ("none", "low", "high"):
            manifest["preflight"]["wire_audits"].append({"model": "gpt-test", "effort": effort,
                "tools": [], "system_matches": True, "user_matches": True, "no_previous_response": True})
            manifest["preflight"]["subscription_probes"].append({"model": "gpt-test", "effort": effort, "events": events("READY")})
        def make_rows(control_hits=False):
            rows = []
            for index, spec in enumerate(plan):
                text = "No clues provided." if spec["condition"] == "control_no_clues" and not control_hits else "ANSWER: " + answers[spec["instance_id"]]
                stream = events(text)
                stream[0]["thread_id"] = f"synthetic-{index}"
                result = {**transport.parse_events(stream, transport.CONDITIONS[spec["condition"]]),
                          "wall_ms": 20, "events": stream}
                with patch("run_gpt_cli_arm.call", return_value=result):
                    rows.append(session(spec, inputs, {}, manifest["manifest_id"]))
            return rows
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runs.jsonl"
            path.with_suffix(".manifest.json").write_text(json.dumps(manifest))
            path.write_text("".join(json.dumps(r) + "\n" for r in make_rows()))
            rows, _, _, _, controls = grade(path)
            self.assertEqual(sum(r["correct"] for r in rows), 18)
            self.assertTrue(all(c["correct"] == 0 for c in controls))
            with patch("sys.argv", ["grade_gpt_runs.py", "--runs", str(path)]):
                grade_main()
            self.assertTrue((Path(folder) / "gpt_cli_arm_tables.md").exists())
            path.write_text("".join(json.dumps(r) + "\n" for r in make_rows(control_hits=True)))
            with self.assertRaisesRegex(ValueError, "control failed"):
                grade(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
