"""Orchestration: run the week, stream the trace, manage the Decision Desk."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from strands.hooks import (
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from .agents import AutonomyGuard, build_graph, make_model, node_text, parse_json, _tool_name
from .events import BUS
from .org import ORG, handbook_search
from .policy import POLICY, PROMOTION_THRESHOLD, Tier
from .scenario import InboundMessage, messages
from .tools import set_context, CURRENT

# How many messages are in flight at once. The pantry's week does not arrive
# one-at-a-time and neither should the demo; concurrency is also what makes the
# trace panel feel alive rather than sequential.
CONCURRENCY = 4


@dataclass
class DecisionCard:
    id: str
    message_id: str
    sender: str
    sim_time: str
    channel: str
    body: str
    decision_class: str
    class_label: str
    tier: str
    headline: str
    why_escalated: str
    recommendation: str
    draft_reply: str
    options: list[dict]
    citations: list[str]
    confidence: float
    status: str = "open"  # open | approved | denied
    resolved_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class TraceCollector(HookProvider):
    """Captures model and tool activity for the live trace panel.

    Hooks fire on whatever thread the graph is running on, so events land in a
    thread-safe deque and an async drainer publishes them. That keeps the
    streaming honest without making the hook itself loop-aware.
    """

    def __init__(self) -> None:
        self.q: deque[dict] = deque(maxlen=4000)
        self._lock = threading.Lock()

    def _push(self, phase: str, **payload: Any) -> None:
        c = CURRENT.get() or {}
        with self._lock:
            # Key is 'phase', not 'kind': BUS.publish wraps this in an envelope
            # that already owns 'kind', and a second 'kind' here would silently
            # overwrite the envelope's.
            self.q.append({
                "phase": phase,
                "message_id": c.get("message_id"),
                "ts": time.time(),
                **payload,
            })

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self._before_model)
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def _before_model(self, event: BeforeModelCallEvent) -> None:
        agent = getattr(event, "agent", None)
        self._push("thinking", node=getattr(agent, "name", "agent"))

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        self._push("tool_call", tool=_tool_name(event))

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        self._push("tool_done", tool=_tool_name(event))

    def drain(self) -> list[dict]:
        with self._lock:
            out = list(self.q)
            self.q.clear()
        return out


class Runtime:
    def __init__(self) -> None:
        self.cards: dict[str, DecisionCard] = {}
        self.model = None
        self.trace = TraceCollector()
        self.guard = AutonomyGuard()
        self.running = False
        self.processed: set[str] = set()
        self.pending_promotion: dict | None = None
        self._lock = threading.RLock()

    def ensure_model(self):
        if self.model is None:
            self.model = make_model()
        return self.model

    def reset(self) -> None:
        with self._lock:
            self.cards.clear()
            self.processed.clear()
            self.pending_promotion = None
        ORG.reset()
        POLICY.reset()
        BUS.clear_history()

    async def _drainer(self, stop: asyncio.Event) -> None:
        """Pump hook events to the browser while the graph runs."""
        while not stop.is_set():
            for ev in self.trace.drain():
                await BUS.publish("trace", ev)
            await asyncio.sleep(0.05)
        for ev in self.trace.drain():
            await BUS.publish("trace", ev)

    async def process_message(self, msg: InboundMessage) -> dict:
        await BUS.publish("message_in", {"message": {
            "id": msg.id, "sim_time": msg.sim_time, "sender": msg.sender,
            "channel": msg.channel, "body": msg.body,
        }})

        model = self.ensure_model()
        graph = build_graph(model, self.guard, msg.id, extra_hooks=[self.trace])

        # Pre-retrieve handbook context. Deterministic, free, and it means the
        # model starts from the right page instead of guessing which to open.
        hits = handbook_search(msg.body)
        context = "\n\n".join(f"### {h['section']}\n{h['text']}" for h in hits)

        task = (
            f"INBOUND MESSAGE\n"
            f"From: {msg.sender}\nChannel: {msg.channel}\nReceived: {msg.sim_time}\n"
            f"Body:\n\"\"\"\n{msg.body}\n\"\"\"\n\n"
            f"POSSIBLY RELEVANT HANDBOOK SECTIONS (verify with search_handbook):\n"
            f"{context}\n"
        )

        # Seed context before the graph starts, so the copy handed to worker
        # threads already carries it. The decision class arrives later, via the
        # routing condition, through CLASSIFICATION.
        set_context(message_id=msg.id, sender=msg.sender, sim_time=msg.sim_time)

        started = time.time()
        try:
            result = await self._invoke(graph, task, msg)
        except Exception as exc:  # noqa: BLE001
            await BUS.publish("message_failed", {
                "message_id": msg.id, "error": f"{type(exc).__name__}: {exc}"[:300]})
            return {"ok": False, "message_id": msg.id, "error": str(exc)}

        elapsed = time.time() - started
        triage_data = parse_json(node_text(result, "triage"))
        cls_key = triage_data.get("decision_class", "")
        cls = POLICY.get(cls_key)
        tier = POLICY.tier_of(cls_key) if cls_key else Tier.ASK

        await BUS.publish("triaged", {
            "message_id": msg.id,
            "decision_class": cls_key,
            "class_label": cls.label if cls else "Unrecognised",
            "tier": tier.value,
            "urgency": triage_data.get("urgency", "routine"),
            "summary": triage_data.get("summary", ""),
            "signals": triage_data.get("signals", []),
        })

        executed = list(getattr(result, "execution_order", []) or [])
        executed_ids = [getattr(n, "node_id", str(n)) for n in executed]

        if "resolver" in executed_ids:
            await BUS.publish("handled", {
                "message_id": msg.id, "decision_class": cls_key,
                "class_label": cls.label if cls else cls_key,
                "sim_time": msg.sim_time, "sender": msg.sender,
                "summary": triage_data.get("summary", ""),
                "reply": _extract_reply(result, msg.id),
                "elapsed": round(elapsed, 1),
            })
            outcome = "handled"
        else:
            card = self._card_from(result, msg, cls_key, cls, tier)
            with self._lock:
                self.cards[card.id] = card
            await BUS.publish("escalated", {"card": card.to_dict()})
            outcome = "escalated"

        self.processed.add(msg.id)
        return {"ok": True, "message_id": msg.id, "outcome": outcome,
                "decision_class": cls_key, "elapsed": elapsed}

    async def _invoke(self, graph, task: str, msg: InboundMessage):
        """Run the graph, keeping ContextVars intact.

        Both paths preserve context: awaiting inside this task shares it
        directly, and asyncio.to_thread copies it into the worker thread. Each
        concurrent message therefore keeps its own message_id.
        """
        invoke_async = getattr(graph, "invoke_async", None)
        if callable(invoke_async):
            return await invoke_async(task)
        return await asyncio.to_thread(graph, task)

    def _card_from(self, result, msg: InboundMessage, cls_key: str,
                   cls, tier: Tier) -> DecisionCard:
        data = parse_json(node_text(result, "escalator"))
        raw = node_text(result, "escalator")

        # Why this reached the Desk is a fact about the policy store, not
        # something the model should be inferring about itself. State it exactly.
        if cls is None:
            why = "Switchboard could not classify this message, so it failed closed to you."
        elif tier is Tier.NEVER:
            why = cls.rationale
        else:
            why = (
                f"{cls.rationale} You haven't delegated this class yet — "
                f"{cls.approvals} of {PROMOTION_THRESHOLD} approvals so far."
            )

        return DecisionCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            message_id=msg.id,
            sender=msg.sender,
            sim_time=msg.sim_time,
            channel=msg.channel,
            body=msg.body,
            decision_class=cls_key or "unknown",
            class_label=cls.label if cls else "Unrecognised — failing closed",
            tier=tier.value,
            headline=data.get("headline") or "Needs your decision",
            why_escalated=why,
            recommendation=data.get("recommendation") or raw[:400],
            draft_reply=data.get("draft_reply", ""),
            options=data.get("options", []) or [],
            citations=data.get("citations", []) or [],
            confidence=float(data.get("confidence", 0.0) or 0.0),
        )

    async def run_week(self, only: list[str] | None = None) -> None:
        if self.running:
            return
        self.running = True
        stop = asyncio.Event()
        drainer = asyncio.create_task(self._drainer(stop))
        await BUS.publish("week_start", {"total": len(messages())})
        started = time.time()

        sem = asyncio.Semaphore(CONCURRENCY)
        msgs = [m for m in messages() if not only or m.id in only]

        async def one(m: InboundMessage):
            async with sem:
                return await self.process_message(m)

        try:
            results = await asyncio.gather(*(one(m) for m in msgs),
                                           return_exceptions=True)
        finally:
            stop.set()
            await drainer
            self.running = False

        handled = sum(1 for r in results
                      if isinstance(r, dict) and r.get("outcome") == "handled")
        escalated = sum(1 for r in results
                        if isinstance(r, dict) and r.get("outcome") == "escalated")
        failed = sum(1 for r in results if not isinstance(r, dict) or not r.get("ok"))

        await BUS.publish("week_done", {
            "handled": handled, "escalated": escalated, "failed": failed,
            "total": len(msgs), "elapsed": round(time.time() - started, 1),
        })

    async def resolve_card(self, card_id: str, action: str,
                           edited_reply: str | None = None) -> dict:
        with self._lock:
            card = self.cards.get(card_id)
            if card is None:
                return {"ok": False, "error": "no such card"}
            if card.status != "open":
                return {"ok": False, "error": "already resolved"}
            modified = bool(edited_reply and edited_reply.strip()
                            and edited_reply.strip() != card.draft_reply.strip())
            card.status = "approved" if action == "approve" else "denied"
            card.resolved_at = datetime.utcnow().isoformat(timespec="seconds")
            if edited_reply:
                card.draft_reply = edited_reply

        if action == "approve":
            ORG.log(
                decision_class=card.decision_class,
                action="Approved by Coordinator" + (" (edited)" if modified else ""),
                detail=card.draft_reply or card.recommendation,
                autonomous=False,
                sim_time=card.sim_time,
                message_id=card.message_id,
                citations=card.citations,
            )
            became_eligible = POLICY.record_approval(card.decision_class, modified)
        else:
            ORG.log(
                decision_class=card.decision_class,
                action="Declined by Coordinator",
                detail=f"Coordinator overrode: {card.recommendation}",
                autonomous=False,
                sim_time=card.sim_time,
                message_id=card.message_id,
            )
            POLICY.record_approval(card.decision_class, modified=True)
            became_eligible = False

        await BUS.publish("card_resolved", {
            "card": card.to_dict(), "modified": modified})
        await BUS.publish("policy", {"classes": POLICY.snapshot()})

        if became_eligible:
            cls = POLICY.get(card.decision_class)
            proposal = {
                "decision_class": card.decision_class,
                "label": cls.label if cls else card.decision_class,
                "approvals": cls.approvals if cls else 0,
                "message": (
                    f"You've approved my last {cls.approvals if cls else 0} "
                    f"“{cls.label if cls else ''}” recommendations without "
                    f"changing a word. Want me to start handling these myself?"
                ),
                "rationale": cls.rationale if cls else "",
            }
            with self._lock:
                self.pending_promotion = proposal
            await BUS.publish("promotion_proposed", proposal)

        return {"ok": True, "card": card.to_dict(),
                "promotion_proposed": became_eligible}

    async def decide_promotion(self, accept: bool) -> dict:
        with self._lock:
            prop = self.pending_promotion
            self.pending_promotion = None
        if not prop:
            return {"ok": False, "error": "no pending promotion"}
        if accept:
            POLICY.promote(prop["decision_class"],
                           datetime.utcnow().isoformat(timespec="seconds"))
            ORG.log(decision_class=prop["decision_class"],
                    action="Autonomy granted",
                    detail=f"Coordinator promoted “{prop['label']}” to autonomous.",
                    autonomous=False, sim_time="")
        await BUS.publish("promotion_resolved",
                          {"accepted": accept, **prop})
        await BUS.publish("policy", {"classes": POLICY.snapshot()})
        return {"ok": True, "accepted": accept}

    async def demote(self, decision_class: str) -> dict:
        ok = POLICY.demote(decision_class)
        if ok:
            ORG.log(decision_class=decision_class, action="Autonomy revoked",
                    detail="Coordinator returned this class to the Decision Desk.",
                    autonomous=False, sim_time="")
            await BUS.publish("policy", {"classes": POLICY.snapshot()})
        return {"ok": ok}

    def state(self) -> dict:
        with self._lock:
            cards = [c.to_dict() for c in self.cards.values()]
        org = ORG.snapshot()
        return {
            "cards": cards,
            "open_cards": sum(1 for c in cards if c["status"] == "open"),
            "policy": POLICY.snapshot(),
            "org": org,
            "running": self.running,
            "pending_promotion": self.pending_promotion,
            "processed": len(self.processed),
            "total": len(messages()),
        }


def _extract_reply(result, message_id: str) -> str:
    """Pull the text the resolver actually sent, for the Ledger feed.

    Must filter by message_id: several messages are in flight at once, so the
    most recent 'Replied' entry in the ledger frequently belongs to a different
    conversation entirely.
    """
    for entry in reversed(ORG.ledger):
        if entry.action == "Replied" and entry.message_id == message_id:
            return entry.detail
    return str(node_text(result, "resolver"))[:400]


RUNTIME = Runtime()
