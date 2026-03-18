# Security Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden RKT Grading Station for production — enforce auth on all API routes, lock down CORS, auto-generate secrets, validate uploads, fix resource leaks and race conditions, sanitize error output.

**Architecture:** Global Starlette middleware for auth enforcement + error sanitization. Targeted fixes for config defaults, file upload validation, PIL resource leaks, threading locks on shared state, and logging gaps.

**Tech Stack:** FastAPI/Starlette middleware, threading.Lock, secrets module, PIL Image lifecycle

---

### Task 1: Security Middleware — Auth Enforcement + Error Sanitization

**Files:**
- Create: `app/middleware/__init__.py`
- Create: `app/middleware/security.py`
- Modify: `app/api/__init__.py:27-32` (add middleware, fix CORS)

**Step 1: Create middleware package init**

Create empty `app/middleware/__init__.py`.

**Step 2: Create security middleware**

Create `app/middleware/security.py`:

```python
"""Security middleware for auth enforcement and error sanitization."""

import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Paths that do NOT require authentication
AUTH_EXEMPT_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/status",
    "/api/docs",
    "/api/docs/oauth2-redirect",
    "/api/openapi.json",
})

# Path prefixes that never need auth (static assets, SPA shell)
NO_AUTH_PREFIXES = ("/static/", "/data/", "/api/docs")


class SecurityMiddleware(BaseHTTPMiddleware):
    """Enforce authentication on /api/* routes and sanitize 500 errors."""

    def __init__(self, app, debug: bool = False):
        super().__init__(app)
        self.debug = debug

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # --- Auth enforcement for API routes ---
        if path.startswith("/api/") and not self._is_exempt(path):
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    {"detail": "Authentication required"},
                    status_code=401,
                )
            token = auth_header[7:]
            from app.api.routes_auth import _verify_token
            payload = _verify_token(token)
            if payload is None:
                return JSONResponse(
                    {"detail": "Invalid or expired token"},
                    status_code=401,
                )

        # --- Call the actual route ---
        response = await call_next(request)

        # --- Error sanitization in production ---
        if not self.debug and response.status_code >= 500:
            logger.error(
                "500 error on %s %s (status %d)",
                request.method, path, response.status_code,
            )
            return JSONResponse(
                {"detail": "Internal server error"},
                status_code=500,
            )

        return response

    @staticmethod
    def _is_exempt(path: str) -> bool:
        if path in AUTH_EXEMPT_PATHS:
            return True
        for prefix in NO_AUTH_PREFIXES:
            if path.startswith(prefix):
                return True
        return False
```

**Step 3: Register middleware and fix CORS in `app/api/__init__.py`**

Replace the CORS block (lines 27-32) with:

```python
    # CORS — restrict to localhost only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://127.0.0.1:{settings.server_port}",
            f"http://localhost:{settings.server_port}",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security middleware — auth enforcement + error sanitization
    from app.middleware.security import SecurityMiddleware
    app.add_middleware(SecurityMiddleware, debug=settings.debug)
```

**Step 4: Verify server starts and unauthenticated requests are blocked**

Run: `python -c "from app.api import create_app; print('OK')"`
Expected: OK (no import errors)

Then start server and test:
```bash
curl -s http://127.0.0.1:8741/api/dashboard/summary
```
Expected: `{"detail":"Authentication required"}` with 401 status

```bash
curl -s http://127.0.0.1:8741/api/auth/login -X POST -H "Content-Type: application/json" -d '{"name":"admin","pin":"1234"}'
```
Expected: 200 with token (login is exempt from auth)

---

### Task 2: Config Hardening — Defaults, Auth Secret, Admin PIN

**Files:**
- Modify: `app/config.py:93-96` (change defaults)
- Modify: `app/api/__init__.py:97-113` (startup hardening)

**Step 1: Change config defaults**

In `app/config.py`, change lines 93-96:

```python
    env: str = "development"
    debug: bool = False
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
```

**Step 2: Harden startup — auto-generate auth secret and admin PIN**

Replace the startup block in `app/api/__init__.py` (lines 88-122) with:

```python
    @app.on_event("startup")
    async def startup():
        import os
        import secrets
        from app.db.database import init_db
        from app.core.logging_config import setup_logging

        setup_logging(app_settings.log_level, Path(app_settings.data_dir))
        logger.info("Starting RKT Grading Station v1.0.0")

        # --- Auto-generate auth secret if using default ---
        if app_settings.auth_secret == "rkt-default-secret-change-me":
            new_secret = secrets.token_hex(32)
            app_settings.auth_secret = new_secret
            _persist_env_var("RKT_AUTH_SECRET", new_secret)
            logger.warning(
                "Auth secret was default — auto-generated and saved to .env. "
                "Existing tokens are now invalid."
            )

        # --- Startup validation warnings ---
        if app_settings.env == "development":
            logger.info("Running in DEVELOPMENT mode (debug=%s)", app_settings.debug)
        if not os.path.exists(".env"):
            logger.warning("No .env file found — using default configuration")

        init_db(app_settings.db.url, echo=app_settings.db.echo)
        logger.info("Database initialized")

        # --- Seed default admin with random PIN ---
        from app.db.database import get_session
        from app.models.operator import Operator
        _seed_db = get_session()
        try:
            if _seed_db.query(Operator).count() == 0:
                import hashlib
                random_pin = f"{secrets.randbelow(900000) + 100000}"
                admin_op = Operator(
                    name="admin",
                    pin_hash=hashlib.sha256(random_pin.encode()).hexdigest(),
                    role="admin",
                )
                _seed_db.add(admin_op)
                _seed_db.commit()
                logger.warning(
                    "Default admin operator created (name='admin', PIN='%s'). "
                    "Change this PIN after first login!",
                    random_pin,
                )
        finally:
            _seed_db.close()

        # Subscribe webhooks to the event bus
        from app.core.events import event_bus, Events
        from app.services.webhook import fire_webhook_background

        event_bus.subscribe(Events.GRADE_APPROVED, lambda d: fire_webhook_background("grade.approved", d))
        event_bus.subscribe(Events.GRADE_OVERRIDDEN, lambda d: fire_webhook_background("grade.overridden", d))
        event_bus.subscribe(Events.AUTH_FLAGGED, lambda d: fire_webhook_background("auth.flagged", d))
        logger.info("Webhook event subscriptions registered")
```

Also add the `_persist_env_var` helper above `create_app()`:

```python
def _persist_env_var(key: str, value: str) -> None:
    """Append or update a variable in the .env file."""
    env_path = Path(".env")
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")
```

**Step 3: Verify startup logs show correct behavior**

Start server, check logs for:
- `"Auth secret was default — auto-generated"` (first run without RKT_AUTH_SECRET in .env)
- `"Default admin operator created (name='admin', PIN='XXXXXX')"` with random 6-digit PIN

---

### Task 3: File Upload Validation

**Files:**
- Modify: `app/api/routes_scan.py:779-808`

**Step 1: Add upload validation**

Replace lines 779-808 in `routes_scan.py` with:

```python
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}
MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


@router.post("/{session_id}/upload")
async def upload_scan_image(session_id: str, side: str = "front", file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a card image for a scan session."""
    from app.models.scan import ScanSession, CardImage
    from app.config import settings

    # --- Validate file extension ---
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}",
        )

    # --- Validate MIME type ---
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid content type '{file.content_type}'. Must be an image.",
        )

    session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    # --- Read and validate size ---
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Maximum: 100 MB.",
        )

    scan_dir = Path(settings.data_dir) / "scans" / session_id
    scan_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{side}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = scan_dir / filename

    with open(file_path, "wb") as f:
        f.write(content)

    image = CardImage(
        session_id=session_id,
        side=side,
        raw_path=str(file_path),
        file_size_bytes=len(content),
    )
    db.add(image)
    db.commit()
    db.refresh(image)

    return {"image_id": image.id, "side": side, "path": str(file_path), "size_bytes": len(content)}
```

**Step 2: Verify by testing upload with invalid file**

```bash
echo "not an image" > /tmp/test.txt
curl -s -X POST "http://127.0.0.1:8741/api/scan/test-session/upload?side=front" -F "file=@/tmp/test.txt"
```
Expected: 400 with "Invalid file type '.txt'"

---

### Task 4: Resource Leak Fixes — PIL Image Handles

**Files:**
- Modify: `app/services/scanner/mock_scanner.py:70`
- Modify: `app/services/scanner/wia_scanner.py:117-118`
- Modify: `app/services/security/verification.py:159-160`

**Step 1: Fix mock_scanner.py — copy image data, close handle**

Replace line 70 in `mock_scanner.py`:

```python
        img = Image.open(file_path).convert("RGB")
```

With:

```python
        with Image.open(file_path) as _img:
            img = _img.convert("RGB")
```

**Step 2: Fix wia_scanner.py — close after load**

Replace lines 117-118 in `wia_scanner.py`:

```python
            img = Image.open(temp_path).convert("RGB")
            img.load()
```

With:

```python
            with Image.open(temp_path) as _raw:
                img = _raw.convert("RGB")
```

Note: `.convert()` returns a new image, so the original file handle is closed by the context manager while the converted image stays in memory.

**Step 3: Fix verification.py — close after decode**

Replace lines 159-160 in `verification.py`:

```python
                img = Image.open(qr_image_path)
                decoded = zbar_decode(img)
```

With:

```python
                with Image.open(qr_image_path) as img:
                    decoded = zbar_decode(img)
```

---

### Task 5: Concurrency Fixes — Threading Locks

**Files:**
- Modify: `app/core/background.py:3,30-33,38,62,66-68,74`
- Modify: `app/core/events.py:1-2,35-36,40,45-46,50-51`

**Step 1: Fix BackgroundTaskRunner — use threading.Lock**

In `background.py`, add `import threading` at the top (line 3 area).

Change the `__init__` (line 30-33):

```python
    def __init__(self, max_workers: int = 4):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.tasks: dict[str, TaskStatus] = {}
        self._lock = threading.Lock()
```

Wrap all `self.tasks` access with the lock:

In `submit()` (line 38):
```python
        with self._lock:
            self.tasks[task_id] = status
```

In `get_status()` (line 62):
```python
        with self._lock:
            return self.tasks.get(task_id)
```

In `update_progress()` (lines 66-68):
```python
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].progress = progress
                self.tasks[task_id].message = message
```

In `cleanup_completed()` (lines 74-78):
```python
        with self._lock:
            now = datetime.now(timezone.utc)
            to_remove = []
            for task_id, status in self.tasks.items():
                if status.completed_at and (now - status.completed_at).total_seconds() > max_age_seconds:
                    to_remove.append(task_id)
            for task_id in to_remove:
                del self.tasks[task_id]
            return len(to_remove)
```

Also in `_run()` inner function (lines 43-55), wrap the status mutations:
```python
        def _run():
            with self._lock:
                status.status = "running"
                status.started_at = datetime.now(timezone.utc)
            try:
                result = fn(*args, **kwargs)
                with self._lock:
                    status.result = result
                    status.status = "completed"
                    status.progress = 1.0
            except Exception as e:
                with self._lock:
                    status.error = str(e)
                    status.status = "failed"
                logger.error(f"Background task {task_id} failed: {e}")
            finally:
                with self._lock:
                    status.completed_at = datetime.now(timezone.utc)
```

**Step 2: Fix EventBus — add threading.Lock**

In `events.py`, add `import threading` at the top.

Add lock to `__init__` (line 35-36):

```python
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()
```

Wrap `subscribe` (line 40):
```python
    def subscribe(self, event_type: str, handler: Callable) -> None:
        with self._lock:
            self._handlers[event_type].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type}")
```

Wrap `unsubscribe` (lines 45-46):
```python
    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        with self._lock:
            if handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)
```

Wrap `publish` read with copy-under-lock (lines 50-51):
```python
    def publish(self, event_type: str, data: Any = None) -> None:
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Event handler {handler.__name__} failed for {event_type}: {e}")
```

---

### Task 6: Error Handling & Logging Improvements

**Files:**
- Modify: `app/api/routes_settings.py:818-851`
- Modify: `app/api/routes_dashboard.py:36-37`
- Modify: `app/services/engraving/engine.py:278,337,362,430`
- Modify: `app/services/security/engine.py:470-472`

**Step 1: Add debug logging to silent excepts in routes_settings.py**

Replace each `except Exception:` + bare assignment (lines 818-851) with pattern:

```python
    except Exception as exc:
        logger.debug("Failed to count %s: %s", "<table_name>", exc)
        tables["<key>"] = 0
```

Apply to all 9 instances. For example the first one becomes:
```python
    try:
        tables["card_records"] = db.query(CardRecord).count()
    except Exception as exc:
        logger.debug("Failed to count card_records: %s", exc)
        tables["card_records"] = 0
```

**Step 2: Add debug logging to routes_dashboard.py:36**

Replace:
```python
    except Exception:
        pass
```
With:
```python
    except Exception as exc:
        logger.debug("Scanner probe failed: %s", exc)
```

**Step 3: Add logging before rollback+raise in engraving engine**

In `app/services/engraving/engine.py`, for the 4 `except Exception:` blocks at lines 278, 337, 362, 430, change each to:

```python
        except Exception:
            logger.exception("Engraving engine operation failed")
            session.rollback()
            raise
```

**Step 4: Same for security engine**

In `app/services/security/engine.py` line 470:

```python
    except Exception:
        logger.exception("Security pattern generation failed")
        db.rollback()
        raise
```

---

### Task 7: Final Verification

**Step 1: Start server and check startup logs**

```bash
python -m uvicorn app.api:create_app --factory --host 127.0.0.1 --port 8741
```

Verify logs show:
- Auth secret auto-generated warning (or correct secret loaded)
- Admin PIN logged on first run
- No import errors or startup crashes

**Step 2: Test auth enforcement**

```bash
# Should fail with 401
curl -s http://127.0.0.1:8741/api/dashboard/summary

# Login should work (exempt)
curl -s -X POST http://127.0.0.1:8741/api/auth/login -H "Content-Type: application/json" -d '{"name":"admin","pin":"<PIN_FROM_LOGS>"}'

# Should work with token
curl -s http://127.0.0.1:8741/api/dashboard/summary -H "Authorization: Bearer <TOKEN>"
```

**Step 3: Test CORS**

```bash
curl -s -I -H "Origin: http://evil.com" http://127.0.0.1:8741/api/auth/login
```
Expected: No `Access-Control-Allow-Origin: http://evil.com` header

**Step 4: Test upload validation**

```bash
# Create a session first (with auth token), then:
echo "not-image" > /tmp/bad.txt
curl -s -X POST "http://127.0.0.1:8741/api/scan/test/upload" -F "file=@/tmp/bad.txt" -H "Authorization: Bearer <TOKEN>"
```
Expected: 400 "Invalid file type"

**Step 5: Verify UI still works**

Open browser to `http://127.0.0.1:8741` — SPA should load (not behind auth). Login via the Operator Login page, then verify all features work with authentication.
