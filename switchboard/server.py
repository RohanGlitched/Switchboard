"""FastAPI surface for Switchboard."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import PROVIDER
from .events import BUS
from .policy import POLICY
from .runtime import RUNTIME
from .scenario import messages

WEB = Path(__file__).parent.parent / "web"

app = FastAPI(title="Switchboard", version="1.0.0")


class ResolveBody(BaseModel):
    action: str
    edited_reply: str | None = None


class PromotionBody(BaseModel):
    accept: bool


class DemoteBody(BaseModel):
    decision_class: str


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "provider": PROVIDER.name,
        "model": PROVIDER.model_id,
        "detail": PROVIDER.detail,
        "live": PROVIDER.is_live,
    }


@app.get("/api/state")
async def state() -> dict:
    s = RUNTIME.state()
    s["provider"] = {"name": PROVIDER.name, "model": PROVIDER.model_id,
                     "detail": PROVIDER.detail, "live": PROVIDER.is_live}
    s["inbox"] = [
        {"id": m.id, "sim_time": m.sim_time, "sender": m.sender,
         "channel": m.channel, "body": m.body}
        for m in messages()
    ]
    return s


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    q = await BUS.subscribe()

    async def gen():
        try:
            yield BUS.sse({"kind": "hello", "provider": PROVIDER.name,
                           "model": PROVIDER.model_id})
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield BUS.sse(ev)
                except asyncio.TimeoutError:
                    # Comment frame keeps proxies from closing an idle stream.
                    yield ": keepalive\n\n"
        finally:
            await BUS.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@app.post("/api/run")
async def run_week() -> dict:
    if RUNTIME.running:
        raise HTTPException(409, "already running")
    if not PROVIDER.is_live:
        # Say what is missing rather than failing somewhere deep in the graph.
        raise HTTPException(503, PROVIDER.detail)
    asyncio.create_task(RUNTIME.run_week())
    return {"ok": True, "started": True}


@app.post("/api/reset")
async def reset() -> dict:
    if RUNTIME.running:
        raise HTTPException(409, "cannot reset while running")
    RUNTIME.reset()
    # Tell every other open tab, or they keep counting a week that is gone.
    await BUS.publish("week_reset", {})
    return {"ok": True}


@app.post("/api/cards/{card_id}/resolve")
async def resolve(card_id: str, body: ResolveBody) -> dict:
    if body.action not in ("approve", "deny"):
        raise HTTPException(400, "action must be 'approve' or 'deny'")
    res = await RUNTIME.resolve_card(card_id, body.action, body.edited_reply)
    if not res.get("ok"):
        raise HTTPException(404, res.get("error", "failed"))
    return res


@app.post("/api/promotion")
async def promotion(body: PromotionBody) -> dict:
    res = await RUNTIME.decide_promotion(body.accept)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error", "no pending promotion"))
    return res


@app.post("/api/demote")
async def demote(body: DemoteBody) -> dict:
    return await RUNTIME.demote(body.decision_class)


@app.get("/api/policy")
async def policy() -> dict:
    return {"classes": POLICY.snapshot()}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/pitch")
async def pitch() -> FileResponse:
    return FileResponse(WEB / "pitch.html")


if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")
