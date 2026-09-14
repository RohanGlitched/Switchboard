"""End-to-end smoke test over a representative slice of the week."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from switchboard.config import PROVIDER            # noqa: E402
from switchboard.events import BUS                 # noqa: E402
from switchboard.org import ORG                    # noqa: E402
from switchboard.policy import POLICY              # noqa: E402
from switchboard.runtime import RUNTIME            # noqa: E402
from switchboard.scenario import by_id             # noqa: E402

# hours -> auto | minor -> NEVER | home-canned -> auto but must decline
# crisis -> NEVER | gluten-free -> ASK | staffing cancel -> auto w/ warning
SLICE = ["m01", "m09", "m11", "m13", "m03", "m21"]


async def main() -> int:
    print(f"provider: {PROVIDER.name} / {PROVIDER.model_id} ({PROVIDER.detail})")
    if not PROVIDER.is_live:
        print("!! No live model provider resolved — aborting smoke test.")
        return 2

    results = []
    for mid in SLICE:
        msg = by_id(mid)
        print(f"\n{'='*72}\n[{msg.sim_time}] {msg.sender} ({msg.channel})")
        print(f"  {msg.body[:130]}")
        r = await RUNTIME.process_message(msg)
        results.append((msg, r))
        if not r.get("ok"):
            print(f"  !! FAILED: {r.get('error')}")
            continue
        got, want = r["decision_class"], msg.expected_class
        mark = "OK " if got == want else "MISS"
        print(f"  [{mark}] class={got} expected={want} -> {r['outcome']} "
              f"({r['elapsed']:.1f}s)")

    print(f"\n{'='*72}\nLEDGER ({len(ORG.ledger)} entries)")
    for e in ORG.ledger:
        print(f"  [{e.sim_time or '--':>9}] {e.action}: {e.detail[:96]}")

    print(f"\nDECISION DESK ({len(RUNTIME.cards)} cards)")
    for c in RUNTIME.cards.values():
        print(f"  - [{c.class_label}] {c.headline}")
        print(f"      why: {c.why_escalated[:100]}")
        print(f"      rec: {c.recommendation[:100]}")
        print(f"      options: {[o.get('label') for o in c.options]}")

    print(f"\nGUARD BLOCKED {len(RUNTIME.guard.blocked)} write attempts: "
          f"{RUNTIME.guard.blocked}")

    ok = sum(1 for m, r in results
             if r.get("ok") and r["decision_class"] == m.expected_class)
    print(f"\nCLASSIFICATION: {ok}/{len(results)} correct")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
