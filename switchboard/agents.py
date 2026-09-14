"""The Switchboard agent system.

Topology (a Strands Graph with conditional routing):

                        ┌─────────────┐
    inbound message ───▶│   triage    │  classify into a decision class
                        └──────┬──────┘
                               │
                 ┌─────────────┴─────────────┐
      tier=AUTO  │                           │  tier=ASK / NEVER
                 ▼                           ▼
        ┌────────────────┐          ┌──────────────────┐
        │   resolver     │          │    escalator     │
        │ acts via tools │          │ drafts Desk card │
        └────────┬───────┘          └────────┬─────────┘
                 │                           │
                 ▼                           ▼
             Ledger                   Decision Desk

The edge condition is the Autonomy Dial. It is evaluated in Python against the
policy store, not decided by a model, because "am I allowed to do this alone?"
must not be a question the model gets to answer about itself.

Defence in depth: the resolver also carries an AutonomyGuard hook that cancels
any write tool whose decision class is not AUTO. If a future prompt change ever
lets a message reach the resolver on the wrong path, the tools still refuse.
"""

from __future__ import annotations

import json
import re
from typing import Any

from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.multiagent import GraphBuilder

from .config import PROVIDER, build_model
from .policy import POLICY, Tier
from .tools import AUTONOMOUS_TOOLS, READ_ONLY, current_class, set_classification

VALID_CLASSES = [c.key for c in POLICY.all()]


class AutonomyGuard(HookProvider):
    """Blocks write tools when the current decision class is not autonomous.

    This is the layer that makes the Autonomy Dial a real control rather than a
    suggestion in a prompt.
    """

    def __init__(self) -> None:
        self.blocked: list[str] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool)

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        name = _tool_name(event)
        if not name or name in READ_ONLY:
            return
        decision_class = current_class()
        if not decision_class:
            # We could not establish what this is. Refuse to write anything.
            self._cancel(
                event,
                name,
                "BLOCKED: no decision class established for this message. "
                "Hand this to the Coordinator.",
            )
            return
        if POLICY.may_act_alone(decision_class):
            return
        tier = POLICY.tier_of(decision_class)
        self.blocked.append(f"{name} ({decision_class})")
        self._cancel(
            event,
            name,
            f"BLOCKED by Autonomy Dial: '{decision_class}' is at tier '{tier.value}'. "
            f"You may not call '{name}' yourself. Summarise the situation and your "
            f"recommendation for the Coordinator instead.",
        )

    @staticmethod
    def _cancel(event: Any, tool_name: str, reason: str) -> None:
        """Stop the tool, or fail loudly.

        Strands cancels a pending tool call by assignment to `event.cancel_tool`.
        If a future version renames that, the assignment could silently land on a
        dead attribute and the write would go through unguarded - which is the one
        outcome this whole system exists to prevent. So we assign, read it back,
        and raise if it did not take. A crashed run is recoverable; a permission
        check that quietly stopped working is not.
        """
        try:
            event.cancel_tool = reason  # type: ignore[attr-defined]
            took = getattr(event, "cancel_tool", None)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"AutonomyGuard could not cancel '{tool_name}': {exc}"
            ) from exc
        if took != reason:
            raise RuntimeError(
                f"AutonomyGuard could not cancel '{tool_name}': setting "
                "BeforeToolCallEvent.cancel_tool had no effect. The Strands hook "
                "API has changed and the guard is not enforcing anything."
            )


def _tool_name(event: Any) -> str:
    for path in ("tool_use", "tool"):
        obj = getattr(event, path, None)
        if obj is None:
            continue
        if isinstance(obj, dict):
            n = obj.get("name")
            if n:
                return str(n)
        n = getattr(obj, "name", None)
        if n:
            return str(n)
    return ""


def parse_json(text: str) -> dict:
    if not text:
        return {}
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # Last resort: first balanced-looking object in the text.
    start = t.find("{")
    if start == -1:
        return {}
    depth = 0
    for i, ch in enumerate(t[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def node_text(state: Any, node_id: str) -> str:
    try:
        nr = state.results.get(node_id)
    except AttributeError:
        return ""
    if nr is None:
        return ""
    return str(getattr(nr, "result", nr))


_CLASS_MENU = "\n".join(
    f"  - {c.key}: {c.description}" for c in POLICY.all()
)

TRIAGE_PROMPT = f"""You are the triage stage of an operations agent for a small \
food pantry. You read one inbound message and classify it. You do not reply to \
anyone and you do not take any action.

Classify into exactly one of these decision classes:
{_CLASS_MENU}

Judge by substance, not tone. A calm, apologetic message can describe a crisis; \
an urgent-sounding one can be a parking question. Specifically:
  - Any mention of having no food now, no formula, no shelter, or personal \
safety is client_crisis, however politely it is phrased.
  - Any volunteer who is or may be under 18 is minor_volunteer.
  - An allergy described as severe, anaphylactic, or EpiPen-level is \
severe_allergy, not a routine dietary_substitution.
  - Journalists, elected officials and their staff are press_media.
  - Home-made, home-canned, or home-preserved food is still a donation question \
- classify it by what it is, and let the next stage apply the rule.

Respond with ONLY this JSON and nothing else:
{{"decision_class": "<one key from the list>",
  "urgency": "routine" | "prompt" | "immediate",
  "summary": "<one sentence, plain language, what this person needs>",
  "signals": ["<short phrase from the message that drove your choice>"]}}"""

RESOLVER_PROMPT = """You are the resolver stage of an operations agent for the \
Riverside Community Pantry. This message has been cleared for you to handle \
alone, end to end.

Work in this order:
  1. Call search_handbook to confirm the governing policy. Do this even when you \
are confident. The handbook overrides any general knowledge you have about how \
food banks usually operate.
  2. Take the concrete action using the tools available - book the shift, record \
the household, accept or decline the donation, apply the substitution.
  3. Call send_reply exactly once to write back to the person.

Rules that are not negotiable:
  - Home-canned, home-preserved, or home-prepared food is always declined. It is \
a state health code matter. Decline it warmly and thank them properly.
  - Never request ID, documentation, proof of income, or immigration status.
  - If a tool returns ok:false, read the error and correct your approach. Do not \
tell the person something succeeded when it did not.
  - If a cancellation drops a shift below minimum staffing, still record it, and \
say plainly in your reply that the shift is now short.

Write like a volunteer who has time for this person, because the whole point of \
you is that someone now does."""

ESCALATOR_PROMPT = """You are the escalation stage of an operations agent for \
the Riverside Community Pantry. This message is NOT yours to resolve. A human \
Coordinator must decide.

Your job is to make that decision take thirty seconds instead of ten minutes. \
You may call search_handbook to gather evidence. You must not contact anyone \
and must not take any action.

A message reaches you for one of two reasons, and it matters which:
  - The class is permanently reserved for a human (safeguarding, crisis, press, \
complaints, severe allergies). These are never yours, however obvious the answer \
looks.
  - The class is one the Coordinator has simply not delegated to you yet. The \
substance may be completely routine. Do not claim it was escalated because it is \
difficult when it was escalated because you have not earned it - say so plainly.

Produce a Decision Desk card as ONLY this JSON:
{"headline": "<8 words or fewer, what must be decided>",
 "why_escalated": "<one sentence: the specific reason a human must own this>",
 "recommendation": "<what you would do, stated plainly and decisively>",
 "draft_reply": "<the message you would send if approved, ready to go>",
 "options": [{"label": "<short action>", "detail": "<consequence of choosing it>"}],
 "citations": ["<handbook section that governs this>"],
 "confidence": <0.0-1.0>}

Give two or three genuinely different options, not one real choice and two straw \
men. Your recommendation should be a real opinion - a Coordinator reading this \
should be able to agree with one click, and should have enough to disagree well.

If the situation involves a person in crisis, the draft_reply must be warm, must \
not promise anything the handbook cannot deliver, and must make clear a human is \
coming."""


def _agent(model, prompt: str, name: str, tools=None, hooks=None) -> Agent:
    kwargs: dict[str, Any] = {
        "system_prompt": prompt,
        "name": name,
        "callback_handler": None,
    }
    if model is not None:
        kwargs["model"] = model
    if tools:
        kwargs["tools"] = tools
    if hooks:
        kwargs["hooks"] = hooks
    return Agent(**kwargs)


def build_graph(model, guard: AutonomyGuard, message_id: str, extra_hooks=None):
    """One Graph per inbound message.

    Rebuilding per message keeps each message's execution independent, which is
    what lets us run the week concurrently without nodes sharing state.
    """
    hooks = [guard] + list(extra_hooks or [])
    triage = _agent(model, TRIAGE_PROMPT, "triage", hooks=list(extra_hooks or []))
    resolver = _agent(model, RESOLVER_PROMPT, "resolver",
                      tools=AUTONOMOUS_TOOLS, hooks=hooks)
    escalator = _agent(model, ESCALATOR_PROMPT, "escalator",
                       tools=[AUTONOMOUS_TOOLS[0]],  # search_handbook only
                       hooks=hooks)

    def classify(state) -> str:
        data = parse_json(node_text(state, "triage"))
        cls = data.get("decision_class", "")
        cls = cls if cls in VALID_CLASSES else ""
        # Publish the verdict where the tools and the guard can see it. The edge
        # condition is the first place in the graph where the class is known.
        set_classification(message_id, cls)
        return cls

    def route_auto(state) -> bool:
        cls = classify(state)
        # Unknown class fails closed to the Coordinator.
        return bool(cls) and POLICY.may_act_alone(cls)

    def route_escalate(state) -> bool:
        return not route_auto(state)

    b = GraphBuilder()
    b.add_node(triage, "triage")
    b.add_node(resolver, "resolver")
    b.add_node(escalator, "escalator")
    b.add_edge("triage", "resolver", condition=route_auto)
    b.add_edge("triage", "escalator", condition=route_escalate)
    b.set_entry_point("triage")
    b.set_max_node_executions(6)
    b.set_execution_timeout(120)
    b.set_node_timeout(60)
    return b.build()


def make_model():
    return build_model(PROVIDER)
