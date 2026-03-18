"""Authentication API routes for operator login."""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# Simple in-memory rate limiter for login attempts
_login_attempts: dict[str, list[float]] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300  # 5 minutes


def _check_rate_limit(identifier: str) -> bool:
    """Returns True if the request is allowed, False if rate limited."""
    now = time.time()
    attempts = _login_attempts.get(identifier, [])
    # Remove attempts outside the window
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
    _login_attempts[identifier] = attempts
    return len(attempts) < _LOGIN_MAX_ATTEMPTS


def _record_attempt(identifier: str) -> None:
    """Record a login attempt."""
    if identifier not in _login_attempts:
        _login_attempts[identifier] = []
    _login_attempts[identifier].append(time.time())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash (supports bcrypt and legacy SHA-256)."""
    import bcrypt
    # Try bcrypt first (new format)
    if hashed.startswith("$2"):
        return bcrypt.checkpw(password.encode(), hashed.encode())
    # Fall back to legacy SHA-256
    return hashed == hashlib.sha256(password.encode()).hexdigest()


def _upgrade_password_if_needed(operator, password: str, db) -> None:
    """Re-hash a legacy SHA-256 password to bcrypt on successful login."""
    if not operator.password_hash.startswith("$2"):
        operator.password_hash = _hash_password(password)
        db.commit()


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
    """Verify token signature and expiration. Returns payload or None."""
    try:
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
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate an operator with username + password."""
    # Rate limiting: max 5 attempts per username per 5 minutes
    if not _check_rate_limit(req.name):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait 5 minutes before trying again.",
        )
    _record_attempt(req.name)

    from app.models.operator import Operator

    operator = db.query(Operator).filter(Operator.name == req.name).first()
    if not operator:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not operator.is_active:
        raise HTTPException(status_code=403, detail="Operator account is deactivated")

    if not _verify_password(req.password, operator.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Auto-upgrade legacy SHA-256 hash to bcrypt
    _upgrade_password_if_needed(operator, req.password, db)

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
async def logout(operator: Optional[dict] = Depends(get_current_operator)):
    """Log out the current operator (client should discard the token)."""
    name = operator["name"] if operator else "unknown"
    logger.info("Operator '%s' logged out", name)
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

    operator = Operator(
        name=req.name,
        password_hash=_hash_password(req.password),
        role=req.role,
    )
    db.add(operator)
    db.commit()
    db.refresh(operator)

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

    operators = db.query(Operator).order_by(Operator.name).all()
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
        operator.password_hash = _hash_password(req.password)

    if req.is_active is not None:
        operator.is_active = req.is_active

    if req.role is not None:
        if req.role not in ("operator", "admin"):
            raise HTTPException(status_code=400, detail="Role must be 'operator' or 'admin'")
        operator.role = req.role

    db.commit()
    db.refresh(operator)

    logger.info("Admin '%s' updated operator '%s'", admin["name"], operator.name)
    return {
        "id": operator.id,
        "name": operator.name,
        "role": operator.role,
        "is_active": operator.is_active,
        "updated_at": operator.updated_at.isoformat() if operator.updated_at else None,
    }
