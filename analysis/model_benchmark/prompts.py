"""Prompt construction — item text is byte-identical to the human screen.

Every string below that a model sees was lifted from `app/run/[token]/Runner.tsx`
or from `instances.json`. Nothing is paraphrased, summarised or "cleaned up".
The only additions are (a) the answer-format instruction, which stands in for
the two radio groups and the Submit button a human used, and (b) the per-
condition reasoning instruction, which is the independent variable.

What a screen-reader participant received, in order:
  intro screen  -> INTRO_* below (read once, before the practice item)
  item screen   -> heading, preamble, "Clues", ordered clue list, question, hint
The 4x4 grid rendered on the item screen is `aria-hidden="true"` (invariants
A3/A3b/A3c), so it never reached a screen-reader participant and is therefore
not given to a model either. Withholding it is the fidelity-preserving choice:
the cohort the study ran on is the cohort whose text this reproduces.
"""

from __future__ import annotations

from items import MAX_ATTEMPTS, Item

# --- Verbatim from Runner.tsx, screen === 'intro' ---------------------------
INTRO_HOW_IT_WORKS = (
    "A circle is hidden in one box of a grid. Each clue tells you where the "
    "circle is not. Rule out boxes until only one is left."
)
INTRO_BOX_NAMING = (
    "A box is named by its column letter and then its row number. B3 means "
    "column B, row 3."
)

# --- Verbatim from Runner.tsx, item screen ----------------------------------
HINT = "Choose the column, then the row, then select Submit."

# --- Verbatim from Runner.tsx, showWrongAnswer() ----------------------------
def wrong_answer_message(attempts_used: int) -> str:
    left = MAX_ATTEMPTS - attempts_used
    if left <= 0:
        return (
            "Your answer was incorrect and you have used all three attempts. "
            "Close this message to move to the next task."
        )
    return (
        f"Your answer was incorrect. You have {left} more "
        f"{'try' if left == 1 else 'tries'}. Close this message, change your "
        "answer, and submit again."
    )


# --- The answer channel -----------------------------------------------------
# A human answered by selecting one column radio and one row radio. A model has
# no radios, so it is told the equivalent in one line. Identical across every
# condition, so it can never explain a between-condition difference.
ANSWER_FORMAT = (
    "Answer with the box name only: one column letter followed by one row "
    'number, for example B3. End your reply with a line of the form '
    '"ANSWER: <box>".'
)

CONDITIONS: dict[str, dict] = {
    # Minimum-token condition. No visible working. This is the cheapest an
    # attacker could possibly solve the item for, and the closest analogue to
    # the single perceptual sweep the asymmetry claim credits to a human.
    "answer_only": {
        "label": "Answer only (no visible working)",
        "instruction": (
            "Reply with the answer line and nothing else. Do not show your "
            "working. Do not include internal or system XML tags in your "
            "response."
        ),
        "thinking": "off",
        "max_tokens": 64,
    },
    # Natural condition. The model reasons in the visible response, so the
    # reasoning cost is measured identically on all three models regardless of
    # how each one configures extended thinking.
    "visible_reasoning": {
        "label": "Visible step-by-step reasoning",
        "instruction": (
            "Work through the clues step by step in your reply, then give the "
            "answer line. Do not include internal or system XML tags in your "
            "response."
        ),
        "thinking": "off",
        "max_tokens": 4000,
    },
    # Deployment-realistic frontier condition: extended thinking as each model
    # ships it. Thinking tokens are billed as output tokens, so usage remains
    # directly comparable.
    "extended_thinking": {
        "label": "Extended thinking (adaptive / budgeted)",
        "instruction": (
            "Give the answer line at the end of your reply."
        ),
        "thinking": "on",
        "max_tokens": 16000,
    },
}


def system_prompt(condition: str) -> str:
    """Intro-screen text plus the answer channel and the condition instruction."""
    cfg = CONDITIONS[condition]
    return "\n\n".join(
        [
            "You are solving a website verification puzzle.",
            INTRO_HOW_IT_WORKS,
            INTRO_BOX_NAMING,
            ANSWER_FORMAT,
            cfg["instruction"],
        ]
    )


def item_prompt(item: Item, position: int, of: int) -> str:
    """The item screen as a screen reader would announce it, in DOM order."""
    heading = "Practice puzzle" if item.is_practice else f"Puzzle {position} of {of}"
    clues = "\n".join(f"{k}. {c}" for k, c in enumerate(item.clues, start=1))
    return "\n".join(
        [
            heading,
            "",
            item.preamble,
            "",
            "Clues",
            clues,
            "",
            item.question,
            HINT,
            "",
            f"Column: {', '.join(item.column_options)}",
            f"Row: {', '.join(item.row_options)}",
        ]
    )


def retry_prompt(attempts_used: int) -> str:
    """The wrong-answer dialog, as the next user turn."""
    return "\n".join(
        ["Incorrect answer", "", wrong_answer_message(attempts_used)]
    )


if __name__ == "__main__":
    from items import load_items

    practice, canonical = load_items()
    for cond in CONDITIONS:
        print("=" * 72)
        print(f"CONDITION: {cond}")
        print("=" * 72)
        print("--- system ---")
        print(system_prompt(cond))
        print()
    print("=" * 72)
    print("--- user turn, practice ---")
    print(item_prompt(practice, 0, 6))
    print()
    print("--- user turn, item 1 of 6 ---")
    print(item_prompt(canonical[0], 1, 6))
    print()
    print("--- user turn, after one wrong answer ---")
    print(retry_prompt(1))
