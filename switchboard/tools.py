"""The agent's hands.

Each tool is a real mutation against OrgState, not a stub that returns a happy
string. Tools return structured results including failures, because an agent
that is told "ok!" no matter what it does cannot learn that it got something
wrong.
"""

from __future__ import annotations

import json
from contextvars import ContextVar

from strands import tool

from .org import ORG, PARTNERS, SERVICE_ZIPS, STOCKED_SUBSTITUTIONS, handbook_search

# The message currently being processed. Tools need it for Ledger attribution,
# and the autonomy guard needs the decision class to decide whether to allow the
# call at all. A ContextVar keeps this correct under asyncio concurrency, where
# several messages are in flight at once.
CURRENT: ContextVar[dict] = ContextVar("current_message", default={})

# Triage's verdict, keyed by message id.
#
# This deliberately does NOT live in the ContextVar. The class is only known
# *after* the triage node runs, and a ContextVar set inside a graph edge
# condition is not reliably visible to the node that runs next - Strands may
# execute nodes on a worker thread or a fresh task, each of which gets a *copy*
# of the context. A plain dict keyed by message id is visible everywhere, and
# single-key assignment is atomic under the GIL, which is all the safety we need.
CLASSIFICATION: dict[str, str] = {}


def set_context(*, message_id: str, sender: str, sim_time: str) -> None:
    CURRENT.set({
        "message_id": message_id,
        "sender": sender,
        "sim_time": sim_time,
    })


def ctx() -> dict:
    return CURRENT.get()


def set_classification(message_id: str, decision_class: str) -> None:
    CLASSIFICATION[message_id] = decision_class


def current_class() -> str:
    return CLASSIFICATION.get(ctx().get("message_id", ""), "")


def clear_classification(message_id: str) -> None:
    CLASSIFICATION.pop(message_id, None)


def _log(action: str, detail: str, citations: list[str] | None = None) -> None:
    c = ctx()
    ORG.log(
        decision_class=current_class() or "unknown",
        action=action,
        detail=detail,
        # Anything a tool does during graph execution was done by the agent on
        # its own. Human-approved actions are logged separately by the runtime.
        autonomous=True,
        sim_time=c.get("sim_time", ""),
        message_id=c.get("message_id"),
        citations=citations,
    )


@tool
def search_handbook(query: str) -> str:
    """Search the pantry's Volunteer & Operations Handbook for relevant policy.

    Always consult this before deciding anything about donations, eligibility,
    volunteers, or accommodations. The handbook governs; your prior assumptions
    about how food banks work do not.

    Args:
        query: What you need to know, e.g. 'home canned food' or 'minimum staffing'.
    """
    hits = handbook_search(query)
    if not hits:
        return json.dumps({"hits": [], "note": "No matching section. Handbook 10 applies: ask the Coordinator."})
    return json.dumps({"hits": hits})


@tool
def book_volunteer_shift(volunteer_name: str, shift_id: str) -> str:
    """Add an adult volunteer to a shift roster.

    Args:
        volunteer_name: Full name of the volunteer.
        shift_id: One of 'mon-sort', 'tue-dist', 'thu-dist', 'sat-dist'.
    """
    res = ORG.add_to_shift(shift_id, volunteer_name)
    if res.get("ok"):
        s = res["shift"]
        _log("Booked volunteer shift",
             f"{volunteer_name} added to {s['name']} ({s['count']}/{s['min_staff']} staffed)")
    return json.dumps(res)


@tool
def cancel_volunteer_shift(volunteer_name: str, shift_id: str) -> str:
    """Remove a volunteer from a shift roster.

    If this drops the shift below its minimum safe staffing, the result will say
    so. That is a staffing risk under handbook 3 and must be raised with the
    Coordinator rather than silently accepted.

    Args:
        volunteer_name: Full name of the volunteer cancelling.
        shift_id: One of 'mon-sort', 'tue-dist', 'thu-dist', 'sat-dist'.
    """
    res = ORG.remove_from_shift(shift_id, volunteer_name)
    if res.get("ok"):
        s = res["shift"]
        note = " — NOW BELOW MINIMUM STAFFING" if res.get("now_understaffed") else ""
        _log("Released volunteer shift",
             f"{volunteer_name} removed from {s['name']} ({s['count']}/{s['min_staff']}){note}")
    return json.dumps(res)


@tool
def register_household(name: str, zip_code: str, notes: str = "") -> str:
    """Register a household for food collection.

    Per handbook 2 we never request ID, proof of income, or immigration status.

    Args:
        name: Name given by the resident.
        zip_code: Their ZIP code.
        notes: Any standing dietary notes to attach to future boxes.
    """
    res = ORG.record_household(name, zip_code, notes)
    if res.get("ok"):
        hh = res["household"]
        _log("Registered household",
             f"{name} ({zip_code}) registered"
             + (f" — standing note: {notes}" if notes else ""),
             citations=["Handbook 2 — no ID or documentation required"])
        if not hh["in_service_area"]:
            res["warning"] = "ZIP is outside the service area; refer to a partner instead."
    return json.dumps(res)


@tool
def refer_to_partner(resident_name: str, zip_code: str) -> str:
    """Refer a resident outside our service ZIPs to a partner organisation.

    Handbook 2: never turn someone away without a specific alternative.

    Args:
        resident_name: The resident's name.
        zip_code: Their ZIP code.
    """
    options = [p for p in PARTNERS if "Citywide" in p["serves"] or "Countywide" in p["serves"]]
    _log("Referred to partner",
         f"{resident_name} ({zip_code}) referred to {options[0]['name'] if options else 'partner network'}",
         citations=["Handbook 8 — Partner Organisations"])
    return json.dumps({"ok": True, "in_service_area": zip_code in SERVICE_ZIPS,
                       "referrals": options or PARTNERS})


@tool
def record_donation_decision(donor: str, description: str, accept: bool, reason: str) -> str:
    """Accept or decline an offered donation, recording why.

    Args:
        donor: Who is offering.
        description: What is being offered.
        accept: True to accept, False to decline.
        reason: The handbook-grounded reason for the decision.
    """
    res = ORG.record_donation(donor, description, accept, reason)
    _log("Accepted donation" if accept else "Declined donation",
         f"{donor}: {description} — {reason}")
    return json.dumps(res)


@tool
def apply_dietary_substitution(household_name: str, substitution: str) -> str:
    """Apply a routine dietary substitution to a household's standing box.

    Only for substitutions we stock (handbook 5). Severe allergies, prescribed
    medical diets, and infant formula are never handled here.

    Args:
        household_name: The household requesting it.
        substitution: e.g. 'gluten-free', 'halal', 'no-added-sugar'.
    """
    normalised = substitution.strip().lower()
    stocked = any(s in normalised or normalised in s for s in STOCKED_SUBSTITUTIONS)
    if not stocked:
        return json.dumps({
            "ok": False,
            "error": f"'{substitution}' is not a stocked routine substitution.",
            "stocked": sorted(STOCKED_SUBSTITUTIONS),
            "note": "Escalate to the Coordinator rather than improvising.",
        })
    _log("Applied dietary substitution",
         f"{household_name}: {substitution} noted on standing box",
         citations=["Handbook 5 — Dietary and Medical Accommodations"])
    return json.dumps({"ok": True, "household": household_name, "substitution": substitution})


@tool
def send_reply(body: str) -> str:
    """Send the reply to the person who messaged the pantry.

    This is the last thing you do. Write it the way a kind, unhurried volunteer
    would: plain words, no jargon, no corporate warmth. Never ask for ID, never
    apologise on the pantry's behalf, and never promise something the handbook
    does not allow.

    Args:
        body: The message to send.
    """
    c = ctx()
    _log("Replied", body.strip())
    return json.dumps({"ok": True, "sent_to": c.get("sender", "unknown"), "body": body.strip()})


AUTONOMOUS_TOOLS = [
    search_handbook,
    book_volunteer_shift,
    cancel_volunteer_shift,
    register_household,
    refer_to_partner,
    record_donation_decision,
    apply_dietary_substitution,
    send_reply,
]

# Tools that only read. The autonomy guard always permits these, because
# gathering evidence is never the risky part.
READ_ONLY = {"search_handbook"}
