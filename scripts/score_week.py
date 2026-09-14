#!/usr/bin/env python3
"""Score triage against ground truth for a week that has already been run.

Usage:
    ./run.sh                                  # in one terminal
    # press "Run the week" in the browser, or:
    curl -s -X POST http://127.0.0.1:8000/api/run
    python scripts/score_week.py              # once the run finishes

Every message carries an `expected_class` in scenario.py. It is never shown to
the agent - it exists only so this number can be checked rather than asserted.

A message's class is recoverable from one of two places: escalated messages
carry it on their Decision Desk card, autonomously handled ones carry it on
their ledger entries. Between them, all 24 are accounted for.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from switchboard.scenario import WEEK  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def main() -> int:
    try:
        with urllib.request.urlopen(f"{BASE}/api/state", timeout=10) as r:
            state = json.load(r)
    except (urllib.error.URLError, OSError) as exc:
        print(f"Could not reach {BASE}: {exc}")
        print("Start the server with ./run.sh and run the week first.")
        return 2

    observed: dict[str, str] = {c["message_id"]: c["decision_class"] for c in state["cards"]}
    for entry in state["org"]["ledger"]:
        observed.setdefault(entry["message_id"], entry["decision_class"])

    expected = {m.id: m.expected_class for m in WEEK}

    correct, wrong, unscored = [], [], []
    for mid, want in sorted(expected.items()):
        got = observed.get(mid)
        if got is None:
            unscored.append(mid)
        elif got == want:
            correct.append(mid)
        else:
            wrong.append((mid, want, got))

    for mid, want, got in wrong:
        print(f"  MISS  {mid}  expected {want!r}, got {got!r}")
    if unscored:
        print(f"  unscored (not processed yet): {', '.join(unscored)}")

    print(f"\n{len(correct)}/{len(expected)} correct"
          f"  ({len(wrong)} wrong, {len(unscored)} unscored)")
    return 0 if not wrong and not unscored else 1


if __name__ == "__main__":
    raise SystemExit(main())
