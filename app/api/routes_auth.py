"""Authentication API routes for operator login."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Rate limiter with bounded LRU storage
# ---------------------------------------------------------------------------

_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300  # 5 minutes
_RATE_LIMIT_MAX_KEYS = 1000


class _LRURateLimiter:
    """Thread-safe LRU-bounded rate limiter.

    Tracks attempts per key (username or IP) with a sliding window.
    Evicts the oldest key when the max size is exceeded.
    """

    def __init__(self, max_keys: int = _RATE_LIMIT_MAX_KEYS):
        self._data: OrderedDict[str, list[float]] = OrderedDict()
        self._max_keys = max_keys
        self._lock = threading.Lock()

    def _prune_window(self, attempts: list[float], now: float) -> list[float]:
        return [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]

    def check(self, identifier: str) -> bool:
        """Returns True if the request is allowed, False if rate limited."""
        now = time.time()
        with self._lock:
            attempts = self._data.get(identifier, [])
            attempts = self._prune_window(attempts, now)
            self._data[identifier] = attempts
            # Move to end (most recently used)
            self._data.move_to_end(identifier)
            return len(attempts) < _LOGIN_MAX_ATTEMPTS

    def record(self, identifier: str) -> None:
        """Record a login attempt for the given identifier."""
        now = time.time()
        with self._lock:
            if identifier not in self._data:
                self._data[identifier] = []
            self._data[identifier].append(now)
            self._data.move_to_end(identifier)
            # Evict oldest keys if over capacity
            while len(self._data) > self._max_keys:
                self._data.popitem(last=False)


_rate_limiter = _LRURateLimiter()

# ---------------------------------------------------------------------------
# Token blacklist for logout revocation
# ---------------------------------------------------------------------------

_token_blacklist: dict[str, float] = {}  # token -> expiration timestamp
_blacklist_lock = threading.Lock()
_BLACKLIST_CLEANUP_INTERVAL = 600  # 10 minutes
_last_blacklist_cleanup: float = 0.0


def _blacklist_token(token: str, exp: float) -> None:
    """Add a token to the blacklist until its natural expiration."""
    with _blacklist_lock:
        _token_blacklist[token] = exp


def _is_token_blacklisted(token: str) -> bool:
    """Check if a token has been revoked."""
    with _blacklist_lock:
        return token in _token_blacklist


def _cleanup_blacklist() -> None:
    """Remove expired tokens from the blacklist."""
    global _last_blacklist_cleanup
    now = time.time()
    if now - _last_blacklist_cleanup < _BLACKLIST_CLEANUP_INTERVAL:
        return
    with _blacklist_lock:
        expired = [t for t, exp in _token_blacklist.items() if exp < now]
        for t in expired:
            del _token_blacklist[t]
        if expired:
            logger.debug("Cleaned %d expired tokens from blacklist", len(expired))
    _last_blacklist_cleanup = now

# ---------------------------------------------------------------------------
# Legacy password tracking
# ---------------------------------------------------------------------------

_legacy_hash_upgrades: int = 0  # count of SHA-256 -> bcrypt upgrades this session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _hash_password_async(password: str) -> str:
    """Hash a password with bcrypt (non-blocking)."""
    import bcrypt
    return await asyncio.to_thread(
        lambda: bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    )


def _hash_password(password: str) -> str:
    """Hash a password with bcrypt (synchronous, for use in sync contexts)."""
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


async def _verify_password_async(password: str, hashed: str) -> bool:
    """Verify a password against its hash, non-blocking (supports bcrypt and legacy SHA-256)."""
    import bcrypt
    if hashed.startswith("$2"):
        return await asyncio.to_thread(
            lambda: bcrypt.checkpw(password.encode(), hashed.encode())
        )
    # Legacy SHA-256 — cheap, no need for to_thread
    return hashed == hashlib.sha256(password.encode()).hexdigest()


async def _upgrade_password_if_needed(operator, password: str, db) -> None:
    """Re-hash a legacy SHA-256 password to bcrypt on successful login."""
    global _legacy_hash_upgrades
    if not operator.password_hash.startswith("$2"):
        logger.warning(
            "Legacy SHA-256 password detected for operator '%s' (id=%s). "
            "Auto-upgrading to bcrypt.",
            operator.name,
            operator.id,
        )
        operator.password_hash = await _hash_password_async(password)
        db.commit()
        _legacy_hash_upgrades += 1
        logger.info(
            "Upgraded operator '%s' password hash to bcrypt "
            "(total legacy upgrades this session: %d)",
            operator.name,
            _legacy_hash_upgrades,
        )


def _get_auth_secret() -> str:
    """Return the auth secret from settings."""
    from app.config import settings
    return settings.auth_secret


def _make_token(operator_id: str, name: str, role: str, ttl: int = 86400) -> str:
    """Create an HMAC-SHA256 signed session token.

    Token structure: base64({payload}).{signature}
    Payload is JSON with operator_id, name, role, exp.
    """
    payload = {
        "operator_id": operator_id,
        "name": name,
        "role": role,
        "exp": int(time.time()) + ttl,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode()
    sig = hmac.new(
        _get_auth_secret().encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def _verify_token(token: str) -> Optional[dict]:
    """Verify token signature, expiration, and blacklist. Returns payload or None."""
    try:
        # Check blacklist before doing any crypto work
        if _is_token_blacklisted(token):
            return None

        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected_sig = hmac.new(
            _get_auth_secret().encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)
        if payload.get("exp", 0) < time.time():
            return None

        # Periodic blacklist cleanup on token verification
        _cleanup_blacklist()

        return payload
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dependency: get_current_operator
# ---------------------------------------------------------------------------

def get_current_operator(authorization: Optional[str] = Header(default=None)) -> Optional[dict]:
    """Extract the current operator from the Authorization header.

    Returns the operator payload dict or None if no valid token is present.
    This does NOT block unauthenticated requests -- the system works
    without login but tracks "default" operator.
    """
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    return _verify_token(token)


def _require_admin(operator: Optional[dict] = Depends(get_current_operator)):
    """Dependency that requires an authenticated admin operator."""
    if not operator:
        raise HTTPException(status_code=401, detail="Authentication required")
    if operator.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return operator


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Operator name")
    password: str = Field(..., min_length=1, description="Password")


class CreateOperatorRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Unique operator name")
    password: str = Field(..., min_length=6, description="Password (min 6 chars)")
    role: str = Field(default="operator", description="'operator' or 'admin'")


class UpdateOperatorRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    password: Optional[str] = Field(default=None, min_length=6)
    is_active: Optional[bool] = None
    role: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/login")
async def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate an operator with username + password."""
    client_ip = request.client.host if request.client else "unknown"

    # Rate limiting: check both username and IP
    if not _rate_limiter.check(f"user:{req.name}"):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait 5 minutes before trying again.",
        )
    if not _rate_limiter.check(f"ip:{client_ip}"):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts from this address. Please wait 5 minutes.",
        )

    # Record attempts for both username and IP
    _rate_limiter.record(f"user:{req.name}")
    _rate_limiter.record(f"ip:{client_ip}")

    from app.models.operator import Operator

    operator = db.query(Operator).filter(Operator.name == req.name).first()
    if not operator:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not operator.is_active:
        raise HTTPException(status_code=403, detail="Operator account is deactivated")

    if not await _verify_password_async(req.password, operator.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Auto-upgrade legacy SHA-256 hash to bcrypt
    await _upgrade_password_if_needed(operator, req.password, db)

    token = _make_token(operator.id, operator.name, operator.role)

    logger.info("Operator '%s' logged in (role=%s)", operator.name, operator.role)
    return {
        "token": token,
        "operator": {
            "id": operator.id,
            "name": operator.name,
            "role": operator.role,
            "is_active": operator.is_active,
        },
    }


@router.post("/logout")
async def logout(
    authorization: Optional[str] = Header(default=None),
    operator: Optional[dict] = Depends(get_current_operator),
):
    """Log out the current operator and revoke the token."""
    name = operator["name"] if operator else "unknown"

    # Revoke the token by adding it to the blacklist
    if authorization and authorization.startswith("Bearer ") and operator:
        token = authorization[7:]
        exp = operator.get("exp", time.time() + 86400)
        _blacklist_token(token, exp)
        logger.info("Operator '%s' logged out — token revoked", name)
    else:
        logger.info("Operator '%s' logged out (no token to revoke)", name)

    return {"status": "logged_out"}


@router.get("/me")
async def me(operator: Optional[dict] = Depends(get_current_operator)):
    """Return the current operator info from the session token."""
    if not operator:
        return {
            "authenticated": False,
            "operator": {
                "id": None,
                "name": "default",
                "role": "operator",
            },
        }
    return {
        "authenticated": True,
        "operator": {
            "id": operator["operator_id"],
            "name": operator["name"],
            "role": operator["role"],
        },
    }


@router.post("/operators")
async def create_operator(
    req: CreateOperatorRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(_require_admin),
):
    """Create a new operator (admin only)."""
    from app.models.operator import Operator

    # Validate role
    if req.role not in ("operator", "admin"):
        raise HTTPException(status_code=400, detail="Role must be 'operator' or 'admin'")

    # Check uniqueness
    existing = db.query(Operator).filter(Operator.name == req.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Operator '{req.name}' already exists")

    try:
        hashed = await _hash_password_async(req.password)
        operator = Operator(
            name=req.name,
            password_hash=hashed,
            role=req.role,
        )
        db.add(operator)
        db.commit()
        db.refresh(operator)
    except Exception:
        logger.exception("Failed to create operator '%s'", req.name)
        raise HTTPException(status_code=500, detail="Internal server error")

    logger.info("Admin '%s' created operator '%s' (role=%s)", admin["name"], req.name, req.role)
    return {
        "id": operator.id,
        "name": operator.name,
        "role": operator.role,
        "is_active": operator.is_active,
        "created_at": operator.created_at.isoformat() if operator.created_at else None,
    }


@router.get("/operators")
async def list_operators(
    db: Session = Depends(get_db),
    admin: dict = Depends(_require_admin),
):
    """List all operators (admin only)."""
    from app.models.operator import Operator

    try:
        operators = db.query(Operator).order_by(Operator.name).all()
    except Exception:
        logger.exception("Failed to list operators")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "count": len(operators),
        "operators": [
            {
                "id": op.id,
                "name": op.name,
                "role": op.role,
                "is_active": op.is_active,
                "created_at": op.created_at.isoformat() if op.created_at else None,
                "updated_at": op.updated_at.isoformat() if op.updated_at else None,
            }
            for op in operators
        ],
    }


@router.put("/operators/{operator_id}")
async def update_operator(
    operator_id: str,
    req: UpdateOperatorRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(_require_admin),
):
    """Update an operator (admin only): change name, reset password, toggle active, change role."""
    from app.models.operator import Operator

    operator = db.query(Operator).filter(Operator.id == operator_id).first()
    if not operator:
        raise HTTPException(status_code=404, detail="Operator not found")

    if req.name is not None:
        # Check uniqueness against other operators
        existing = db.query(Operator).filter(
            Operator.name == req.name, Operator.id != operator_id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Name '{req.name}' is already taken")
        operator.name = req.name

    if req.password is not None:
        operator.password_hash = await _hash_password_async(req.password)

    if req.is_active is not None:
        operator.is_active = req.is_active

    if req.role is not None:
        if req.role not in ("operator", "admin"):
            raise HTTPException(status_code=400, detail="Role must be 'operator' or 'admin'")
        operator.role = req.role

    try:
        db.commit()
        db.refresh(operator)
    except Exception:
        logger.exception("Failed to update operator '%s'", operator_id)
        raise HTTPException(status_code=500, detail="Internal server error")

    logger.info("Admin '%s' updated operator '%s'", admin["name"], operator.name)
    return {
        "id": operator.id,
        "name": operator.name,
        "role": operator.role,
        "is_active": operator.is_active,
        "updated_at": operator.updated_at.isoformat() if operator.updated_at else None,
    }
