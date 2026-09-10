"""Item loading, verification and independent solving for the model benchmark.

The benchmark must run on *exactly* the items the human participants saw. That
is the practice item plus `canonical_set` (band 2, 4x4, four clues, fixed
order), resolved out of `data/instances.json` by the same rules the app applies
in `lib/instances.ts`. Nothing here selects, filters or re-orders items on its
own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_PATH = REPO_ROOT / "data" / "instances.json"

# Mirrors lib/instances.ts. A human had three attempts per item, so the model
# gets three; anything else measures a different task.
MAX_ATTEMPTS = 3
ITEMS_PER_PARTICIPANT = 6


@dataclass(frozen=True)
class Item:
    instance_id: str
    n: int
    preamble: str
    question: str
    clues: tuple[str, ...]
    column_options: tuple[str, ...]
    row_options: tuple[str, ...]
    solution: str
    difficulty_band: int
    n_clues: int
    n_constraints: int
    human_sweeps: int
    model_cell_checks: int
    asymmetry_ratio: int
    is_practice: bool

    @property
    def cells_total(self) -> int:
        return self.n * self.n


def _item(raw: dict, *, is_practice: bool) -> Item:
    return Item(
        instance_id=raw["instance_id"],
        n=raw["n"],
        preamble=raw["preamble"],
        question=raw["question"],
        clues=tuple(raw["clues"]),
        column_options=tuple(raw["column_options"]),
        row_options=tuple(raw["row_options"]),
        solution=raw["solution"],
        difficulty_band=raw["difficulty_band"],
        n_clues=raw["n_clues"],
        n_constraints=raw["n_constraints"],
        human_sweeps=raw["human_sweeps"],
        model_cell_checks=raw["model_cell_checks"],
        asymmetry_ratio=raw["asymmetry_ratio"],
        is_practice=is_practice,
    )


def load_bundle(path: Path | None = None) -> dict:
    return json.loads((path or BUNDLE_PATH).read_text())


def load_items(path: Path | None = None) -> tuple[Item, list[Item]]:
    """Return (practice, canonical_six) with the app's own invariants enforced."""
    bundle = load_bundle(path)

    unverified = [
        i["instance_id"]
        for i in [bundle["practice"], *bundle["instances"]]
        if i.get("uniqueness_verified") != 1
    ]
    if unverified:
        raise SystemExit(f"Unverified instances: {', '.join(unverified)}")
    if len(bundle["canonical_set"]) != ITEMS_PER_PARTICIPANT:
        raise SystemExit("canonical_set must be 6")

    by_id = {i["instance_id"]: i for i in bundle["instances"]}
    canonical = []
    for iid in bundle["canonical_set"]:
        if iid not in by_id:
            raise SystemExit(f"canonical_set references missing instance {iid}")
        canonical.append(_item(by_id[iid], is_practice=False))

    return _item(bundle["practice"], is_practice=True), canonical


# --- Independent solver -----------------------------------------------------
# The bundle asserts each instance is unique and minimal. We re-derive the
# answer from the clue *text* rather than trusting the `solution` field, so a
# model marked wrong is wrong against a second, independent reading of the
# puzzle. This is also what produces the human-sweep / cell-check counts the
# asymmetry claim rests on.

def _cells(n: int) -> list[str]:
    return ["ABCDEFG"[c] + str(r) for r in range(1, n + 1) for c in range(n)]


def _survives(cell: str, clue: str, n: int) -> bool:
    """Apply one negative clue to one cell. True means the cell is still alive."""
    col, row = cell[0], int(cell[1:])
    text = clue.rstrip(".")

    cols = {c for c in ("ABCDEFG"[:n]) if f"column {c}" in text}
    rows = {r for r in range(1, n + 1) if f"row {r}" in text}

    if "touching the edge of the grid" in text:
        return not (col in ("ABCDEFG"[0], "ABCDEFG"[n - 1]) or row in (1, n))
    if "middle" in text and "boxes" in text:
        mid_cols = "ABCDEFG"[1 : n - 1]
        return not (col in mid_cols and 1 < row < n)
    if "diagonal" in text:
        idx = "ABCDEFG".index(col)
        on_main = idx == row - 1
        on_anti = idx == n - row
        if "either diagonal" in text:
            return not (on_main or on_anti)
        return not on_main
    if cols:
        return col not in cols
    if rows:
        return row not in rows

    raise ValueError(f"unparsed clue: {clue!r}")


def solve(item: Item) -> list[str]:
    """Every cell consistent with all clues. Length 1 for a valid instance."""
    return [
        cell
        for cell in _cells(item.n)
        if all(_survives(cell, clue, item.n) for clue in item.clues)
    ]


def verify(items: Iterable[Item]) -> list[str]:
    """Return human-readable problems; empty list means every item checks out."""
    problems = []
    for item in items:
        survivors = solve(item)
        if len(survivors) != 1:
            problems.append(
                f"{item.instance_id}: {len(survivors)} surviving cells {survivors}"
            )
        elif survivors[0] != item.solution:
            problems.append(
                f"{item.instance_id}: solver says {survivors[0]}, "
                f"bundle says {item.solution}"
            )
    return problems


if __name__ == "__main__":
    practice, canonical = load_items()
    problems = verify([practice, *canonical])
    for item in [practice, *canonical]:
        print(
            f"{item.instance_id}  band {item.difficulty_band}  "
            f"{item.n}x{item.n}  {item.n_clues} clues  -> {item.solution}"
        )
    print()
    print("PROBLEMS:", problems or "none - all solutions independently confirmed")
