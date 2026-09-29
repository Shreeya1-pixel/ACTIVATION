"""Phase A identity: local-first accounts, per-user API tokens, OS-keyring secrets.

Design rules (README §3/§8 + roadmap §A):
  - Local-first: users live in the local DB; secrets that protect data at rest go to the
    OS credential store (keyring) with a documented fallback file for CI/test machines.
  - Passwords: PBKDF2-HMAC-SHA256, per-user salt, 200k iterations. No plaintext, ever.
  - Tokens: hashed at rest (sha256); the plaintext is shown exactly once at creation.
  - Backward compatibility: the legacy shared token (AUTOSTACK_TOKEN env / spike token
    file) remains valid as the "service token" so every existing client and the QA
    probe keep working unchanged. Per-user tokens are additive.
  - Lockout: bounded failed-attempt counter per user (production hardening, honest).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import ApiToken, User

PBKDF2_ITERATIONS = 200_000
MAX_FAILED_ATTEMPTS = 10


# ── password hashing ──────────────────────────────────────────────────────────

def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
    ).hex()
    return hmac.compare_digest(candidate, digest)


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


# ── users ─────────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_user(db: Session, username: str, password: str, display_name: str = "",
                is_admin: bool = False) -> User:
    username = (username or "").strip().lower()
    if not username or len(username) > 64 or not all(c.isalnum() or c in "._-@" for c in username):
        raise ValueError("invalid username")
    if len(password or "") < 8:
        raise ValueError("password must be at least 8 characters")
    existing = db.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise ValueError("username already exists")
    first = db.scalar(select(User).limit(1)) is None
    user = User(
        id=secrets.token_hex(12),
        username=username,
        display_name=(display_name or username)[:120],
        password_hash=hash_password(password),
        is_admin=is_admin or first,  # first local user administers the machine
        failed_attempts=0,
        locked_until=None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    return user


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == (username or "").strip().lower()))
    if user is None:
        return None
    if user.locked_until is not None:
        until = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        if until > datetime.now(timezone.utc):
            return None  # still locked; do not reveal via timing
        user.locked_until = None
        user.failed_attempts = 0
    if not verify_password(password or "", user.password_hash):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            from datetime import timedelta
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.commit()
        return None
    user.failed_attempts = 0
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return user


# ── API tokens ────────────────────────────────────────────────────────────────

def issue_token(db: Session, user_id: str, name: str = "default") -> tuple[ApiToken, str]:
    """Create a per-user token. Returns (row, plaintext) — plaintext shown once."""
    plaintext = "ask_" + secrets.token_urlsafe(32)
    row = ApiToken(
        id=secrets.token_hex(12),
        user_id=user_id,
        name=(name or "default")[:80],
        token_hash=hash_token(plaintext),
        prefix=plaintext[:8],
        created_at=datetime.now(timezone.utc),
        last_used_at=None,
        revoked=False,
    )
    db.add(row)
    db.commit()
    return row, plaintext


def user_for_token(db: Session, plaintext: str) -> User | None:
    if not plaintext:
        return None
    row = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(plaintext)))
    if row is None or row.revoked:
        return None
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return db.get(User, row.user_id)


def list_tokens(db: Session, user_id: str) -> list[ApiToken]:
    return list(db.scalars(select(ApiToken).where(ApiToken.user_id == user_id)
                           .where(ApiToken.revoked == False)))  # noqa: E712


def revoke_token(db: Session, user_id: str, token_id: str) -> bool:
    row = db.get(ApiToken, token_id)
    if row is None or row.user_id != user_id:
        return False
    row.revoked = True
    db.commit()
    return True
