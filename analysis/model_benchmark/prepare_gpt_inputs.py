#!/usr/bin/env python3
"""Export ONLY the human-visible prompts. No model is called by this process."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from items import load_items, verify
from prompts import item_prompt, system_prompt

HERE = Path(__file__).resolve().parent


def strip_clues(prompt: str) -> str:
    before, rest = prompt.split("\nClues\n", 1)
    _, after = rest.split("\n\n", 1)
    return before + "\nClues\n(none provided)\n\n" + after


def export() -> dict:
    practice, canonical = load_items()
    problems = verify([practice, *canonical])
    if problems:
        raise ValueError("Independent item verification failed; export aborted.")
    rows = []
    for position, item in enumerate([practice, *canonical]):
        prompt = item_prompt(item, position, len(canonical))
        # Explicit allowlist. Never serialize an Item or the source bundle.
        rows.append({
            "instance_id": item.instance_id, "is_practice": item.is_practice,
            "n": item.n, "prompt": prompt,
            "control_prompt": strip_clues(prompt),
        })
    return {"schema_version": 1, "system": system_prompt("extended_thinking"),
            "items": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "gpt_inputs.json")
    args = parser.parse_args()
    payload = json.dumps(export(), indent=2, ensure_ascii=False) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload)
    print(f"Exported 6 test prompts + practice; no answer fields -> {args.out}")
    print("SHA256:", hashlib.sha256(payload.encode()).hexdigest())


if __name__ == "__main__":
    main()
