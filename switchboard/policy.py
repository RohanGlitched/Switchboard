"""The Autonomy Dial.

The premise of Switchboard: an agent should not arrive pre-trusted. It earns
each piece of its autonomy from the human it works for, one decision class at a
time, and it can be demoted the instant it gets one wrong.

Three tiers:
    AUTO  - the agent acts alone and logs it to the Ledger.
    ASK   - the agent does the work but parks it on the Decision Desk.
    NEVER - the agent may never act alone, no matter how many times a human
            agrees with it. Liability, safeguarding, and crisis calls live here.

That NEVER tier is the important one. A trust system that can promote anything
given enough repetitions is a trust system that will eventually automate telling
a fourteen-year-old they can work the distribution floor. Some decisions are not
the agent's to make, and the ceiling is encoded in the policy, not the prompt.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

STORE = Path(__file__).parent / "_policy_store.json"

# How many times a human must approve an agent recommendation *unmodified*
# before the agent is allowed to ask for promotion.
PROMOTION_THRESHOLD = 3


class Tier(str, Enum):
    AUTO = "auto"
    ASK = "ask"
    NEVER = "never"


@dataclass
class DecisionClass:
    key: str
    label: str
    description: str
    tier: Tier
    promotable: bool
    # Why this class sits where it does - shown in the UI so the human can audit
    # the agent's boundaries rather than take them on faith.
    rationale: str
    approvals: int = 0
    modifications: int = 0
    promoted_at: str | None = None

    @property
    def eligible_for_promotion(self) -> bool:
        return (
            self.promotable
            and self.tier is Tier.ASK
            and self.approvals >= PROMOTION_THRESHOLD
        )


def _seed() -> dict[str, DecisionClass]:
    d = [
        DecisionClass(
            "hours_question", "Hours & location questions",
            "Someone asks when we're open or where we are.",
            Tier.AUTO, True,
            "Pure handbook lookup. Wrong answers are cheap and self-correcting.",
        ),
        DecisionClass(
            "volunteer_signup", "Volunteer shift signup",
            "An adult volunteer claims an open shift.",
            Tier.AUTO, True,
            "Reversible in one message, and an over-staffed shift harms nobody.",
        ),
        DecisionClass(
            "volunteer_cancel", "Volunteer cancellation",
            "A volunteer drops a shift they had claimed.",
            Tier.AUTO, True,
            "Recorded automatically - but a cancellation that drops a shift below "
            "the handbook's 4-person minimum is re-routed to the Desk as a staffing risk.",
        ),
        DecisionClass(
            "client_intake", "New household intake",
            "A resident inside our service ZIPs asks for food.",
            Tier.AUTO, True,
            "The handbook is unambiguous: no ID, no proof, no questions. There is "
            "nothing here for a human to decide.",
        ),
        DecisionClass(
            "partner_referral", "Out-of-area referral",
            "A resident outside our ZIPs needs a partner pantry.",
            Tier.AUTO, True,
            "Table lookup against the partner list in the handbook.",
        ),
        DecisionClass(
            "donation_standard", "Standard shelf-stable donation",
            "Sealed, in-date, commercially packaged goods on the accepted list.",
            Tier.AUTO, True,
            "Explicitly pre-authorised by handbook 4.1.",
        ),
        DecisionClass(
            "dietary_substitution", "Routine dietary substitution",
            "Gluten-free, low-sodium, halal, vegetarian, no-added-sugar swaps.",
            Tier.ASK, True,
            "We stock all of these and the swap is routine - but it touches what a "
            "family eats, so the agent starts by asking and earns this one.",
        ),
        DecisionClass(
            "donation_bestby", "Past 'best by', not 'use by'",
            "Quality-dated goods that are very often still perfectly good.",
            Tier.ASK, True,
            "A judgment call about quality and current stock, not a safety rule.",
        ),
        DecisionClass(
            "donation_perishable", "Perishable donation",
            "Dairy, meat, refrigerated prepared food.",
            Tier.ASK, True,
            "Constrained by exactly one refrigerator. Accepting what we cannot "
            "store converts a donation into landfill.",
        ),
        DecisionClass(
            "donation_homemade", "Home-made or home-canned food",
            "Jam, chutney, baking, preserves - anything prepared in a home kitchen.",
            Tier.ASK, True,
            "The answer is always no under state health code, but it is offered "
            "with real generosity and often by someone who already gives us time "
            "and money. Refusing it badly costs more than the food is worth.",
        ),
        DecisionClass(
            "donation_bulk", "Bulk or corporate donation",
            "Over ~200lbs, a pallet, or any business or school drive.",
            Tier.ASK, True,
            "Logistics we may not be able to physically receive, and an ongoing "
            "relationship the Coordinator owns.",
        ),
        # ---- The ceiling. These never move. ----
        DecisionClass(
            "minor_volunteer", "Volunteer under 18",
            "Any inquiry involving a volunteer who is a minor.",
            Tier.NEVER, False,
            "Insurance and safeguarding. Handbook 3.1 makes this non-delegable, "
            "and no number of correct past answers should change that.",
        ),
        DecisionClass(
            "severe_allergy", "Severe allergy or medical diet",
            "Anaphylactic allergies, prescribed diets, infant formula.",
            Tier.NEVER, False,
            "A substitution error here can put someone in hospital.",
        ),
        DecisionClass(
            "client_crisis", "Household in crisis",
            "No food today, no shelter, no formula, or any safety disclosure.",
            Tier.NEVER, False,
            "A person in crisis gets a person. This is the whole point of the "
            "agent handling everything else.",
        ),
        DecisionClass(
            "complaint", "Complaint or incident",
            "Conduct complaints, discrimination, food quality or safety reports.",
            Tier.NEVER, False,
            "Handbook 9. The agent must never apologise on the pantry's behalf "
            "or concede fault.",
        ),
        DecisionClass(
            "press_media", "Press or public official",
            "Media, elected officials, public records requests.",
            Tier.NEVER, False,
            "Handbook 7. No volunteer - and no agent - speaks for the pantry.",
        ),
    ]
    return {c.key: c for c in d}


class PolicyStore:
    """Thread-safe autonomy policy. Strands session managers are not thread-safe
    and neither is this, so all mutation goes through one lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._classes = _seed()
        self._load()

    # ---------- persistence ----------
    def _load(self) -> None:
        if not STORE.exists():
            return
        try:
            raw = json.loads(STORE.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for key, saved in raw.items():
            cls = self._classes.get(key)
            if not cls:
                continue
            # Never let a persisted file promote something past its ceiling.
            tier = Tier(saved.get("tier", cls.tier.value))
            if not cls.promotable and tier is not cls.tier:
                tier = cls.tier
            cls.tier = tier
            cls.approvals = saved.get("approvals", 0)
            cls.modifications = saved.get("modifications", 0)
            cls.promoted_at = saved.get("promoted_at")

    def save(self) -> None:
        with self._lock:
            payload = {
                k: {
                    "tier": c.tier.value,
                    "approvals": c.approvals,
                    "modifications": c.modifications,
                    "promoted_at": c.promoted_at,
                }
                for k, c in self._classes.items()
            }
        try:
            STORE.write_text(json.dumps(payload, indent=2))
        except OSError:
            pass

    def reset(self) -> None:
        with self._lock:
            self._classes = _seed()
        STORE.unlink(missing_ok=True)

    # ---------- queries ----------
    def get(self, key: str) -> DecisionClass | None:
        return self._classes.get(key)

    def tier_of(self, key: str) -> Tier:
        cls = self._classes.get(key)
        # Unknown class => ask a human. Failing closed is the only safe default.
        return cls.tier if cls else Tier.ASK

    def may_act_alone(self, key: str) -> bool:
        return self.tier_of(key) is Tier.AUTO

    def all(self) -> list[DecisionClass]:
        return list(self._classes.values())

    def snapshot(self) -> list[dict]:
        with self._lock:
            out = []
            for c in self._classes.values():
                d = asdict(c)
                d["tier"] = c.tier.value
                d["eligible_for_promotion"] = c.eligible_for_promotion
                d["threshold"] = PROMOTION_THRESHOLD
                out.append(d)
            return out

    # ---------- mutation ----------
    def record_approval(self, key: str, modified: bool) -> bool:
        """Log a human verdict. Returns True if the class just became eligible
        for promotion (i.e. the agent has earned the right to ask)."""
        with self._lock:
            cls = self._classes.get(key)
            if cls is None or cls.tier is not Tier.ASK:
                return False
            if modified:
                # A human edit means the agent's judgment was not yet good
                # enough. Trust resets - it does not merely pause.
                cls.modifications += 1
                cls.approvals = 0
                self.save()
                return False
            was_eligible = cls.eligible_for_promotion
            cls.approvals += 1
            self.save()
            return cls.eligible_for_promotion and not was_eligible

    def promote(self, key: str, when: str) -> bool:
        with self._lock:
            cls = self._classes.get(key)
            if cls is None or not cls.promotable or cls.tier is not Tier.ASK:
                return False
            cls.tier = Tier.AUTO
            cls.promoted_at = when
            self.save()
            return True

    def demote(self, key: str) -> bool:
        with self._lock:
            cls = self._classes.get(key)
            if cls is None or cls.tier is not Tier.AUTO:
                return False
            cls.tier = Tier.ASK
            cls.approvals = 0
            cls.promoted_at = None
            self.save()
            return True


POLICY = PolicyStore()
