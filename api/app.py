"""FastAPI application for the CarHero mobile API.

Mounted at /api/v1 by main.py (dual deploy with FastHTML).
Also runnable standalone: python -m api.app
"""

from __future__ import annotations

import json
import logging
import secrets

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.auth import create_token
from api.deps import get_db, get_current_user
from api.schemas import (
    LoginRequest, RegisterRequest, AuthResponse, UserInfo,
    ChatRequest, SessionSummary, SessionDetail, MessageOut, ShareResponse,
    AgentOut,
)
from auth.utils import hash_password, verify_password

log = logging.getLogger(__name__)

SCHEMA = "carhero"


def create_app(root_path: str = "") -> FastAPI:
    """Build the FastAPI app. Routes have no /api/v1 prefix — that comes from the mount point."""
    api = FastAPI(
        title="CarHero API",
        description="Mobile API for CarHero — EU car marketplace with AI advisors",
        version="1.0.0",
        root_path=root_path,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health ────────────────────────────────────────────────────────

    @api.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    # ── Auth ──────────────────────────────────────────────────────────

    @api.post("/auth/register", response_model=AuthResponse, tags=["auth"])
    def register(body: RegisterRequest, db: Session = Depends(get_db)):
        existing = db.execute(
            text(f"SELECT id, password_hash FROM {SCHEMA}.chat_users WHERE email = :email"),
            {"email": body.email},
        ).fetchone()

        if existing and existing.password_hash:
            raise HTTPException(409, "An account with this email already exists")

        pw_hash = hash_password(body.password)

        if existing:
            db.execute(
                text(f"UPDATE {SCHEMA}.chat_users SET password_hash = :pw, name = :name, is_verified = TRUE WHERE email = :email"),
                {"pw": pw_hash, "name": body.name, "email": body.email},
            )
            db.commit()
            uid = existing.id
        else:
            row = db.execute(
                text(f"INSERT INTO {SCHEMA}.chat_users (email, password_hash, name, is_verified) "
                     "VALUES (:email, :pw, :name, TRUE) RETURNING id"),
                {"email": body.email, "pw": pw_hash, "name": body.name},
            ).fetchone()
            db.commit()
            uid = row[0]

        token = create_token(uid, body.email)
        return AuthResponse(token=token, email=body.email, name=body.name, user_id=uid)

    @api.post("/auth/login", response_model=AuthResponse, tags=["auth"])
    def login(body: LoginRequest, db: Session = Depends(get_db)):
        row = db.execute(
            text(f"SELECT id, email, password_hash, name FROM {SCHEMA}.chat_users WHERE email = :email"),
            {"email": body.email},
        ).fetchone()

        if not row or not row.password_hash:
            raise HTTPException(401, "Invalid email or password")
        if not verify_password(body.password, row.password_hash):
            raise HTTPException(401, "Invalid email or password")

        token = create_token(row.id, row.email)
        return AuthResponse(token=token, email=row.email, name=row.name or "", user_id=row.id)

    @api.get("/auth/me", response_model=UserInfo, tags=["auth"])
    def me(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
        row = db.execute(
            text(f"SELECT id, email, name FROM {SCHEMA}.chat_users WHERE id = :id"),
            {"id": user["user_id"]},
        ).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        return UserInfo(user_id=row.id, email=row.email, name=row.name or "")

    # ── Agents ────────────────────────────────────────────────────────

    @api.get("/agents", response_model=list[AgentOut], tags=["agents"])
    def list_agents():
        from agents.registry import AGENTS
        return [
            AgentOut(
                slug=a.slug, name=a.name, category=a.category,
                icon=a.icon, one_liner=a.one_liner, prefix=a.prefix,
                example_prompts=list(a.example_prompts),
            )
            for a in AGENTS
        ]

    # ── Sessions ──────────────────────────────────────────────────────

    @api.get("/sessions", response_model=list[SessionSummary], tags=["sessions"])
    def list_sessions(
        limit: int = 30,
        user: dict = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        rows = db.execute(
            text(f"SELECT id, title, agent_slug, updated_at FROM {SCHEMA}.chat_sessions "
                 "WHERE user_id = :uid ORDER BY updated_at DESC LIMIT :lim"),
            {"uid": user["user_id"], "lim": limit},
        ).fetchall()
        return [
            SessionSummary(id=r.id, title=r.title, agent_slug=r.agent_slug,
                           updated_at=str(r.updated_at))
            for r in rows
        ]

    @api.get("/sessions/{session_id}", response_model=SessionDetail, tags=["sessions"])
    def get_session(
        session_id: int,
        user: dict = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        row = db.execute(
            text(f"SELECT id, title, agent_slug FROM {SCHEMA}.chat_sessions WHERE id = :sid AND user_id = :uid"),
            {"sid": session_id, "uid": user["user_id"]},
        ).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")

        msgs = db.execute(
            text(f"SELECT role, content, agent_slug FROM {SCHEMA}.chat_messages "
                 "WHERE session_id = :sid ORDER BY id ASC"),
            {"sid": session_id},
        ).fetchall()
        return SessionDetail(
            id=row.id, title=row.title, agent_slug=row.agent_slug,
            messages=[MessageOut(role=m.role, content=m.content, agent_slug=m.agent_slug) for m in msgs],
        )

    @api.delete("/sessions/{session_id}", tags=["sessions"])
    def delete_session(
        session_id: int,
        user: dict = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        row = db.execute(
            text(f"SELECT id FROM {SCHEMA}.chat_sessions WHERE id = :sid AND user_id = :uid"),
            {"sid": session_id, "uid": user["user_id"]},
        ).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")

        db.execute(text(f"DELETE FROM {SCHEMA}.chat_messages WHERE session_id = :sid"), {"sid": session_id})
        db.execute(text(f"DELETE FROM {SCHEMA}.chat_sessions WHERE id = :sid"), {"sid": session_id})
        db.commit()
        return {"ok": True}

    @api.post("/sessions/{session_id}/share", response_model=ShareResponse, tags=["sessions"])
    def share_session(
        session_id: int,
        user: dict = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        row = db.execute(
            text(f"SELECT share_token FROM {SCHEMA}.chat_sessions WHERE id = :sid AND user_id = :uid"),
            {"sid": session_id, "uid": user["user_id"]},
        ).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")

        token = row.share_token
        if not token:
            token = secrets.token_urlsafe(32)
            db.execute(
                text(f"UPDATE {SCHEMA}.chat_sessions SET share_token = :token WHERE id = :sid"),
                {"token": token, "sid": session_id},
            )
            db.commit()
        return ShareResponse(token=token, url=f"/shared/{token}")

    # ── Chat (SSE streaming) ─────────────────────────────────────────

    @api.post("/chat", tags=["chat"],
              responses={200: {"content": {"text/event-stream": {}},
                               "description": "SSE stream of chat events"}})
    def chat(
        body: ChatRequest,
        user: dict = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        uid = user["user_id"]

        if body.session_id:
            row = db.execute(
                text(f"SELECT id FROM {SCHEMA}.chat_sessions WHERE id = :sid AND user_id = :uid"),
                {"sid": body.session_id, "uid": uid},
            ).fetchone()
            session_id = row.id if row else None
        else:
            session_id = None

        if not session_id:
            row = db.execute(
                text(f"INSERT INTO {SCHEMA}.chat_sessions (user_id, title) VALUES (:uid, :title) RETURNING id"),
                {"uid": uid, "title": body.message[:80]},
            ).fetchone()
            db.commit()
            session_id = row[0]

        from agents import router as agent_router
        from agents.registry import by_slug
        agent_slug = agent_router.route(body.message)
        spec = by_slug(agent_slug)

        db.execute(
            text(f"INSERT INTO {SCHEMA}.chat_messages (session_id, role, content) VALUES (:sid, 'user', :content)"),
            {"sid": session_id, "content": body.message},
        )
        db.commit()

        history_rows = db.execute(
            text(f"SELECT role, content FROM {SCHEMA}.chat_messages "
                 "WHERE session_id = :sid ORDER BY id ASC"),
            {"sid": session_id},
        ).fetchall()
        history = [{"role": r.role, "content": r.content} for r in history_rows[:-1]]

        stripped_msg = agent_router.strip_prefix(body.message)

        async def event_stream():
            from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
            from utils.i18n import LANGUAGES

            yield _sse_event("session", {"sid": session_id})
            yield _sse_event("agent_route", {
                "slug": agent_slug,
                "agent": spec.name if spec else agent_slug,
                "icon": spec.icon if spec else "*",
            })

            lang_info = LANGUAGES.get(body.lang, LANGUAGES["en"])
            lang_directive = ""
            if body.lang != "en":
                lang_directive = f"\nUser language: {body.lang} ({lang_info['name']}). Respond in {lang_info['name']}."

            lc_messages = [SystemMessage(content=f"You are a CarHero car advisor. Respond helpfully and concisely.{lang_directive}")]
            for h in history[-20:]:
                if h["role"] == "user":
                    lc_messages.append(HumanMessage(content=h["content"]))
                elif h["role"] == "assistant":
                    lc_messages.append(AIMessage(content=h["content"]))
            lc_messages.append(HumanMessage(content=stripped_msg))

            accumulated = []
            tool_calls_log = []

            try:
                from agents.base import cached_agent
                graph = cached_agent(agent_slug)

                async for ev in graph.astream_events({"messages": lc_messages}, version="v2"):
                    kind = ev["event"]
                    if kind == "on_chat_model_stream":
                        chunk = ev["data"].get("chunk")
                        if chunk and hasattr(chunk, "content") and isinstance(chunk.content, str) and chunk.content:
                            if not getattr(chunk, "tool_call_chunks", None):
                                accumulated.append(chunk.content)
                                yield _sse_event("token", {"text": chunk.content})
                    elif kind == "on_tool_start":
                        name = ev.get("name", "unknown")
                        args = ev["data"].get("input", {})
                        tool_calls_log.append({"name": name, "args": args})
                        yield _sse_event("tool_start", {"name": name, "args": args})
                    elif kind == "on_tool_end":
                        name = ev.get("name", "unknown")
                        raw = ev["data"].get("output", "")
                        output = getattr(raw, "content", None) or (raw if isinstance(raw, str) else str(raw))
                        yield _sse_event("tool_end", {"name": name, "output": output[:2000]})

                        if isinstance(output, str) and "__ARTIFACT__" in output:
                            try:
                                artifact_str = output[output.index("__ARTIFACT__") + len("__ARTIFACT__"):]
                                sep = artifact_str.find("\n\n")
                                if sep != -1:
                                    artifact_str = artifact_str[:sep]
                                payload = json.loads(artifact_str)
                                yield _sse_event("artifact_show", payload)
                            except Exception:
                                pass
            except Exception as e:
                log.exception("chat stream failed")
                yield _sse_event("error", {"message": str(e)})

            final = "".join(accumulated) or "(no response)"

            from db import SessionLocal
            persist_db = SessionLocal()
            try:
                persist_db.execute(
                    text(f"INSERT INTO {SCHEMA}.chat_messages (session_id, role, content, agent_slug, tool_calls) "
                         "VALUES (:sid, 'assistant', :content, :agent, :tools)"),
                    {"sid": session_id, "content": final, "agent": agent_slug,
                     "tools": json.dumps(tool_calls_log) if tool_calls_log else None},
                )
                persist_db.execute(
                    text(f"UPDATE {SCHEMA}.chat_sessions SET agent_slug = :slug, updated_at = now() WHERE id = :sid"),
                    {"slug": agent_slug, "sid": session_id},
                )
                persist_db.commit()
            finally:
                persist_db.close()

            yield _sse_event("done", {"slug": agent_slug, "tools": len(tool_calls_log)})

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return api


def _sse_event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"


# App instance for mounting in main.py
api_router = create_app()


if __name__ == "__main__":
    import uvicorn
    standalone = create_app(root_path="/api/v1")
    uvicorn.run(standalone, host="0.0.0.0", port=5012)
