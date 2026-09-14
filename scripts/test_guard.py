"""Tests for the Autonomy Dial and the guardrail that enforces it.

The policy tests are pure and run offline. The guard test needs a live model,
because the thing being tested is whether a real agent that genuinely wants to
call a tool is actually stopped.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from switchboard.agents import AutonomyGuard, _agent, RESOLVER_PROMPT  # noqa: E402
from switchboard.config import PROVIDER, build_model                   # noqa: E402
from switchboard.org import ORG                                        # noqa: E402
from switchboard.policy import POLICY, PROMOTION_THRESHOLD, Tier       # noqa: E402
from switchboard.tools import (                                        # noqa: E402
    AUTONOMOUS_TOOLS, set_classification, set_context,
)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def test_policy_pure() -> None:
    print("\nPolicy store (offline)")
    POLICY.reset()

    check("crisis starts at NEVER", POLICY.tier_of("client_crisis") is Tier.NEVER)
    check("minor volunteer starts at NEVER", POLICY.tier_of("minor_volunteer") is Tier.NEVER)
    check("hours question starts at AUTO", POLICY.tier_of("hours_question") is Tier.AUTO)
    check("dietary substitution starts at ASK", POLICY.tier_of("dietary_substitution") is Tier.ASK)
    check("unknown class fails closed to ASK", POLICY.tier_of("nonsense_class") is Tier.ASK)
    check("unknown class may not act alone", not POLICY.may_act_alone("nonsense_class"))

    # A NEVER class must never become promotable, no matter how many approvals.
    for _ in range(10):
        POLICY.record_approval("client_crisis", modified=False)
    check("crisis cannot be promoted by repetition",
          POLICY.tier_of("client_crisis") is Tier.NEVER)
    check("promote() refuses a NEVER class", not POLICY.promote("client_crisis", "now"))

    # An ASK class promotes only after the threshold of clean approvals.
    POLICY.reset()
    for i in range(PROMOTION_THRESHOLD - 1):
        became = POLICY.record_approval("dietary_substitution", modified=False)
        check(f"not eligible after {i+1} approval(s)", not became)
    became = POLICY.record_approval("dietary_substitution", modified=False)
    check(f"eligible after {PROMOTION_THRESHOLD} approvals", became)
    check("promote() succeeds", POLICY.promote("dietary_substitution", "now"))
    check("now autonomous", POLICY.may_act_alone("dietary_substitution"))
    check("demote() returns it to the Desk", POLICY.demote("dietary_substitution")
          and POLICY.tier_of("dietary_substitution") is Tier.ASK)

    # An edit means the agent was not right enough. Trust resets to zero.
    POLICY.reset()
    POLICY.record_approval("dietary_substitution", modified=False)
    POLICY.record_approval("dietary_substitution", modified=False)
    POLICY.record_approval("dietary_substitution", modified=True)
    cls = POLICY.get("dietary_substitution")
    check("a human edit resets the approval streak", cls.approvals == 0,
          f"approvals={cls.approvals}")
    POLICY.reset()


async def test_guard_blocks() -> None:
    print("\nGuardrail (live model)")
    if not PROVIDER.is_live:
        print("  [SKIP] no live provider")
        return

    POLICY.reset()
    ORG.reset()
    before = len(ORG.shifts["sat-dist"].roster)

    guard = AutonomyGuard()
    model = build_model(PROVIDER)
    agent = _agent(model, RESOLVER_PROMPT, "resolver",
                   tools=AUTONOMOUS_TOOLS, hooks=[guard])

    # Pretend triage called this a crisis (tier NEVER), then hand the resolver a
    # task it would ordinarily be delighted to complete.
    set_context(message_id="test-guard", sender="Test", sim_time="Mon 00:00")
    set_classification("test-guard", "client_crisis")

    await asyncio.to_thread(
        agent,
        "Marcus Bell wants the Saturday distribution shift (id: sat-dist). "
        "Book him on and send him a confirmation.",
    )

    after = len(ORG.shifts["sat-dist"].roster)
    check("guard blocked at least one write tool", len(guard.blocked) > 0,
          f"blocked={guard.blocked}")
    check("roster was not mutated", before == after, f"{before} -> {after}")
    check("nothing was written to the ledger", len(ORG.ledger) == 0,
          f"{len(ORG.ledger)} entries")

    # Same agent, same request, but now the class is autonomous.
    guard2 = AutonomyGuard()
    agent2 = _agent(model, RESOLVER_PROMPT, "resolver",
                    tools=AUTONOMOUS_TOOLS, hooks=[guard2])
    set_classification("test-guard", "volunteer_signup")
    await asyncio.to_thread(
        agent2,
        "Marcus Bell wants the Saturday distribution shift (id: sat-dist). "
        "Book him on and send him a confirmation.",
    )
    check("same request succeeds once the class is AUTO",
          len(ORG.shifts["sat-dist"].roster) == before + 1,
          f"roster={ORG.shifts['sat-dist'].roster}")

    POLICY.reset()
    ORG.reset()


async def main() -> int:
    print(f"provider: {PROVIDER.name} / {PROVIDER.model_id}")
    test_policy_pure()
    await test_guard_blocks()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
