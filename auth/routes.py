"""Authentication routes: register, login, verify, forgot password, reset, profile, Google OAuth."""

from __future__ import annotations

import logging
import os
import urllib.parse
from datetime import datetime, timedelta

import requests as http_requests

from fasthtml.common import (
    Html, Head, Body, Div, H2, H3, P, A, Button, Form, Input, Label, Script, NotStr,
)
from starlette.responses import RedirectResponse, JSONResponse

from auth.utils import (
    hash_password, verify_password, generate_token,
    send_verification_email, send_reset_email,
)
from chat.layout import _head
from utils.session import get_user_email, set_user_email, get_user_id, set_user_id, clear_user

log = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("SERVICE_URL_CARHERO", "https://carhero.chat") + "/auth/google/callback"

SCHEMA = "carhero"


def _get_db():
    from db import SessionLocal
    return SessionLocal()


def register_auth_routes(rt):

    @rt("/auth/register")
    def post(request):
        """Register a new user."""
        import asyncio
        return asyncio.ensure_future(_register(request))

    @rt("/auth/register", methods=["POST"])
    async def auth_register(request):
        from sqlalchemy import text
        form = await request.form()
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""
        name = (form.get("name") or "").strip()

        if not email or not password:
            return JSONResponse({"error": "Email and password are required"}, status_code=400)
        if len(password) < 6:
            return JSONResponse({"error": "Password must be at least 6 characters"}, status_code=400)

        db = _get_db()
        try:
            existing = db.execute(
                text(f"SELECT id, password_hash FROM {SCHEMA}.chat_users WHERE email = :email"),
                {"email": email},
            ).fetchone()

            if existing and existing.password_hash:
                return JSONResponse({"error": "An account with this email already exists"}, status_code=409)

            token = generate_token()
            pw_hash = hash_password(password)

            if existing:
                db.execute(text(f"""
                    UPDATE {SCHEMA}.chat_users
                    SET password_hash = :pw, name = :name, verify_token = :token, is_verified = FALSE
                    WHERE email = :email
                """), {"pw": pw_hash, "name": name, "token": token, "email": email})
            else:
                db.execute(text(f"""
                    INSERT INTO {SCHEMA}.chat_users (email, password_hash, name, verify_token, is_verified)
                    VALUES (:email, :pw, :name, :token, FALSE)
                """), {"email": email, "pw": pw_hash, "name": name, "token": token})
            db.commit()
        finally:
            db.close()

        send_verification_email(email, token, name)
        return JSONResponse({"ok": True, "message": "Check your email to verify your account"})

    @rt("/auth/verify/{token}")
    def auth_verify(token: str, sess):
        from sqlalchemy import text
        db = _get_db()
        try:
            row = db.execute(
                text(f"SELECT id, email FROM {SCHEMA}.chat_users WHERE verify_token = :token"),
                {"token": token},
            ).fetchone()
            if not row:
                return Html(_head("Verification"), Body(
                    Div(H2("Invalid or expired link"), P("Please register again."),
                        cls="max-w-md mx-auto mt-20 text-center"),
                    cls="bg-white font-sans",
                ))
            db.execute(text(f"""
                UPDATE {SCHEMA}.chat_users
                SET is_verified = TRUE, verify_token = NULL
                WHERE id = :id
            """), {"id": row.id})
            db.commit()

            set_user_email(sess, row.email)
            set_user_id(sess, row.id)
        finally:
            db.close()

        return RedirectResponse("/app", status_code=303)

    @rt("/auth/login", methods=["POST"])
    async def auth_login(request, sess):
        from sqlalchemy import text
        form = await request.form()
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""

        if not email or not password:
            return JSONResponse({"error": "Email and password are required"}, status_code=400)

        db = _get_db()
        try:
            row = db.execute(
                text(f"SELECT id, email, password_hash, is_verified, name FROM {SCHEMA}.chat_users WHERE email = :email"),
                {"email": email},
            ).fetchone()
        finally:
            db.close()

        if not row:
            return JSONResponse({"error": "Invalid email or password"}, status_code=401)

        if not row.password_hash:
            return JSONResponse({"error": "no_password", "message": "Please set a password for your account"}, status_code=401)

        if not verify_password(password, row.password_hash):
            return JSONResponse({"error": "Invalid email or password"}, status_code=401)

        set_user_email(sess, row.email)
        set_user_id(sess, row.id)
        return JSONResponse({"ok": True, "email": row.email, "name": row.name or ""})

    @rt("/auth/forgot", methods=["POST"])
    async def auth_forgot(request):
        from sqlalchemy import text
        form = await request.form()
        email = (form.get("email") or "").strip().lower()
        if not email:
            return JSONResponse({"error": "Email is required"}, status_code=400)

        db = _get_db()
        try:
            row = db.execute(
                text(f"SELECT id FROM {SCHEMA}.chat_users WHERE email = :email"),
                {"email": email},
            ).fetchone()
            if row:
                token = generate_token()
                expires = datetime.utcnow() + timedelta(hours=1)
                db.execute(text(f"""
                    UPDATE {SCHEMA}.chat_users
                    SET reset_token = :token, reset_token_expires = :expires
                    WHERE id = :id
                """), {"token": token, "expires": expires, "id": row.id})
                db.commit()
                send_reset_email(email, token)
        finally:
            db.close()

        return JSONResponse({"ok": True, "message": "If an account exists, a reset link has been sent"})

    @rt("/auth/reset/{token}")
    def auth_reset_page(token: str):
        from sqlalchemy import text
        db = _get_db()
        try:
            row = db.execute(
                text(f"SELECT id FROM {SCHEMA}.chat_users WHERE reset_token = :token AND reset_token_expires > NOW()"),
                {"token": token},
            ).fetchone()
        finally:
            db.close()

        if not row:
            return Html(_head("Reset Password"), Body(
                Div(H2("Invalid or expired link"), P("Please request a new reset link."),
                    A("Back to login", href="/app", cls="text-black font-semibold"),
                    cls="max-w-md mx-auto mt-20 text-center"),
                cls="bg-white font-sans",
            ))

        return Html(_head("Reset Password"), Body(
            Div(
                H2("Set new password", cls="text-xl font-bold mb-4"),
                Form(
                    Input(type="password", name="password", placeholder="New password (min 6 chars)",
                          cls="w-full px-3 py-2 border border-gray-200 rounded-md text-sm mb-3", required=True),
                    Input(type="password", name="password_confirm", placeholder="Confirm password",
                          cls="w-full px-3 py-2 border border-gray-200 rounded-md text-sm mb-4", required=True),
                    Button("Reset Password", type="submit",
                           cls="w-full py-2 bg-black text-white rounded-md text-sm cursor-pointer border-none"),
                    id="reset-form",
                    method="POST",
                    action=f"/auth/reset/{token}/submit",
                ),
                Div(id="reset-error", cls="text-red-500 text-sm mt-2"),
                cls="max-w-sm mx-auto mt-20 p-6 bg-white rounded-lg border border-gray-200",
            ),
            cls="bg-gray-50 font-sans min-h-screen",
        ))

    @rt("/auth/reset/{token}/submit", methods=["POST"])
    async def auth_reset_submit(token: str, request, sess):
        from sqlalchemy import text
        form = await request.form()
        password = form.get("password") or ""
        password_confirm = form.get("password_confirm") or ""

        if len(password) < 6:
            return RedirectResponse(f"/auth/reset/{token}", status_code=303)
        if password != password_confirm:
            return RedirectResponse(f"/auth/reset/{token}", status_code=303)

        db = _get_db()
        try:
            row = db.execute(
                text(f"SELECT id, email FROM {SCHEMA}.chat_users WHERE reset_token = :token AND reset_token_expires > NOW()"),
                {"token": token},
            ).fetchone()
            if not row:
                return RedirectResponse("/app", status_code=303)

            pw_hash = hash_password(password)
            db.execute(text(f"""
                UPDATE {SCHEMA}.chat_users
                SET password_hash = :pw, reset_token = NULL, reset_token_expires = NULL, is_verified = TRUE
                WHERE id = :id
            """), {"pw": pw_hash, "id": row.id})
            db.commit()

            set_user_email(sess, row.email)
            set_user_id(sess, row.id)
        finally:
            db.close()

        return RedirectResponse("/app", status_code=303)

    @rt("/auth/logout", methods=["POST"])
    def auth_logout(sess):
        clear_user(sess)
        return JSONResponse({"ok": True})

    @rt("/auth/set-password", methods=["POST"])
    async def auth_set_password(request, sess):
        from sqlalchemy import text
        form = await request.form()
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""

        if not email or len(password) < 6:
            return JSONResponse({"error": "Email and password (min 6 chars) required"}, status_code=400)

        db = _get_db()
        try:
            row = db.execute(
                text(f"SELECT id FROM {SCHEMA}.chat_users WHERE email = :email AND password_hash IS NULL"),
                {"email": email},
            ).fetchone()
            if not row:
                return JSONResponse({"error": "Account not found or already has password"}, status_code=404)

            pw_hash = hash_password(password)
            db.execute(text(f"""
                UPDATE {SCHEMA}.chat_users
                SET password_hash = :pw, is_verified = TRUE
                WHERE id = :id
            """), {"pw": pw_hash, "id": row.id})
            db.commit()

            set_user_email(sess, email)
            set_user_id(sess, row.id)
        finally:
            db.close()

        return JSONResponse({"ok": True, "email": email})

    @rt("/app/profile")
    def profile_page(sess):
        from sqlalchemy import text
        email = get_user_email(sess)
        if not email:
            return RedirectResponse("/app", status_code=303)

        uid = get_user_id(sess)
        db = _get_db()
        try:
            row = db.execute(
                text(f"SELECT name, email, created_at FROM {SCHEMA}.chat_users WHERE id = :id"),
                {"id": uid},
            ).fetchone()
        finally:
            db.close()

        name = row.name or "" if row else ""
        user_email = row.email if row else email

        return Html(_head("Profile"), Body(
            Div(
                A("< Back to chat", href="/app", cls="text-sm text-gray-500 mb-4 block"),
                H2("Profile", cls="text-xl font-bold mb-6"),
                Form(
                    Div(
                        Label("Name", cls="text-xs text-gray-500 block mb-1"),
                        Input(type="text", name="name", value=name, placeholder="Your name",
                              cls="w-full px-3 py-2 border border-gray-200 rounded-md text-sm mb-3"),
                    ),
                    Div(
                        Label("Email", cls="text-xs text-gray-500 block mb-1"),
                        Input(type="email", name="email", value=user_email, disabled=True,
                              cls="w-full px-3 py-2 border border-gray-200 rounded-md text-sm mb-3 bg-gray-50"),
                    ),
                    H3("Change Password", cls="text-sm font-semibold mt-4 mb-2"),
                    Input(type="password", name="current_password", placeholder="Current password",
                          cls="w-full px-3 py-2 border border-gray-200 rounded-md text-sm mb-2"),
                    Input(type="password", name="new_password", placeholder="New password (min 6 chars)",
                          cls="w-full px-3 py-2 border border-gray-200 rounded-md text-sm mb-4"),
                    Div(
                        Button("Save", type="submit",
                               cls="px-6 py-2 bg-black text-white rounded-md text-sm cursor-pointer border-none"),
                        id="profile-msg", cls="inline-block ml-3 text-sm",
                    ),
                    id="profile-form",
                    onsubmit="return submitProfile(event)",
                ),
                cls="max-w-md mx-auto mt-12 p-6",
            ),
            Script(NotStr("""
                async function submitProfile(e) {
                    e.preventDefault();
                    const form = document.getElementById('profile-form');
                    const resp = await fetch('/app/profile', {
                        method: 'POST',
                        body: new FormData(form),
                    });
                    const data = await resp.json();
                    const msg = document.getElementById('profile-msg');
                    if (data.ok) msg.textContent = 'Saved!';
                    else msg.textContent = data.error || 'Error';
                    setTimeout(() => msg.textContent = '', 3000);
                    return false;
                }
            """)),
            cls="bg-white font-sans min-h-screen",
        ))

    @rt("/app/profile", methods=["POST"])
    async def profile_update(request, sess):
        from sqlalchemy import text
        uid = get_user_id(sess)
        if not uid:
            return JSONResponse({"error": "Not logged in"}, status_code=401)

        form = await request.form()
        name = (form.get("name") or "").strip()
        current_password = form.get("current_password") or ""
        new_password = form.get("new_password") or ""

        db = _get_db()
        try:
            updates = ["name = :name"]
            params = {"name": name, "id": uid}

            if new_password:
                if len(new_password) < 6:
                    return JSONResponse({"error": "New password must be at least 6 characters"}, status_code=400)
                row = db.execute(
                    text(f"SELECT password_hash FROM {SCHEMA}.chat_users WHERE id = :id"),
                    {"id": uid},
                ).fetchone()
                if row and row.password_hash:
                    if not verify_password(current_password, row.password_hash):
                        return JSONResponse({"error": "Current password is incorrect"}, status_code=400)
                params["pw"] = hash_password(new_password)
                updates.append("password_hash = :pw")

            db.execute(text(f"""
                UPDATE {SCHEMA}.chat_users SET {', '.join(updates)} WHERE id = :id
            """), params)
            db.commit()
        finally:
            db.close()

        return JSONResponse({"ok": True})

    # ─── Google OAuth ─────────────────────────────────────────────────────────

    @rt("/auth/google")
    def auth_google_redirect(sess):
        if not GOOGLE_CLIENT_ID:
            return JSONResponse({"error": "Google OAuth not configured"}, status_code=500)

        state = generate_token()
        sess["oauth_state"] = state

        params = urllib.parse.urlencode({
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "state": state,
            "prompt": "select_account",
        })
        return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}", status_code=302)

    @rt("/auth/google/callback")
    def auth_google_callback(request, sess):
        from sqlalchemy import text

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            log.warning(f"Google OAuth error: {error}")
            return RedirectResponse("/app", status_code=303)

        if not code or state != sess.get("oauth_state"):
            log.warning("Google OAuth: invalid state or missing code")
            return RedirectResponse("/app", status_code=303)

        sess.pop("oauth_state", None)

        token_resp = http_requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        if token_resp.status_code != 200:
            log.error(f"Google token exchange failed: {token_resp.text}")
            return RedirectResponse("/app", status_code=303)

        tokens = token_resp.json()
        access_token = tokens.get("access_token")

        userinfo_resp = http_requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if userinfo_resp.status_code != 200:
            log.error(f"Google userinfo failed: {userinfo_resp.text}")
            return RedirectResponse("/app", status_code=303)

        userinfo = userinfo_resp.json()
        email = userinfo.get("email", "").lower().strip()
        name = userinfo.get("name", "")

        if not email:
            return RedirectResponse("/app", status_code=303)

        db = _get_db()
        try:
            row = db.execute(
                text(f"SELECT id, email, name FROM {SCHEMA}.chat_users WHERE email = :email"),
                {"email": email},
            ).fetchone()

            if row:
                if not row.name and name:
                    db.execute(text(f"UPDATE {SCHEMA}.chat_users SET name = :name WHERE id = :id"),
                               {"name": name, "id": row.id})
                    db.commit()
                uid = row.id
            else:
                result = db.execute(text(f"""
                    INSERT INTO {SCHEMA}.chat_users (email, name, is_verified)
                    VALUES (:email, :name, TRUE)
                    RETURNING id
                """), {"email": email, "name": name})
                uid = result.fetchone().id
                db.commit()

            set_user_email(sess, email)
            set_user_id(sess, uid)
        finally:
            db.close()

        return RedirectResponse("/app", status_code=303)
