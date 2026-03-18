# Security Hardening & Production Readiness

**Date:** 2026-03-08
**Scope:** Critical fixes + Production readiness
**Approach:** Hybrid — global middleware for cross-cutting concerns, targeted fixes for code-level issues

## Audit Findings Summary

| Severity | Issue | Location |
|----------|-------|----------|
| CRITICAL | Auth optional on all routes | `routes_auth.py:81-93` |
| CRITICAL | Default auth secret hardcoded | `config.py:124` |
| CRITICAL | Default admin PIN `1234` | `__init__.py:106` |
| CRITICAL | CORS `allow_origins=["*"]` | `__init__.py:29` |
| CRITICAL | Race condition — BackgroundTaskRunner lock unused | `background.py:32-33` |
| HIGH | No file type/size validation on uploads | `routes_scan.py:779-808` |
| HIGH | PIL Image handles never closed | `mock_scanner.py`, `wia_scanner.py`, `verification.py` |
| HIGH | Exception details leaked in HTTP 500 responses | Multiple route files |
| HIGH | EventBus handlers unsynchronized | `events.py:36-50` |
| MEDIUM | 10 silent `except: pass` blocks | `routes_settings.py`, `routes_dashboard.py` |
| MEDIUM | 4 rollback-without-logging patterns | `engraving/engine.py`, `security/engine.py` |
| MEDIUM | debug=True and log_level=DEBUG as defaults | `config.py:94,96` |

## Design

### 1. Security Middleware (`app/middleware/security.py`)

New Starlette middleware added in `create_app()`:

**Auth enforcement:**
- All `/api/*` requests require valid `Authorization: Bearer <token>` header
- Exempt paths: `/api/auth/login`, `/api/auth/status`, `/api/docs`
- Invalid/missing token → 401 JSON response
- Replaces current optional auth on every route

**Error sanitization (production mode):**
- If `settings.debug == False` and response status >= 500, replace body with generic error message
- Real error details logged server-side only
- In debug mode, details pass through unchanged for developer visibility

### 2. CORS & Config Hardening

**CORS (`__init__.py`):**
- Replace `allow_origins=["*"]` with `["http://127.0.0.1:8741", "http://localhost:8741"]`
- Desktop app only needs localhost access

**Config defaults (`config.py`):**
- `debug: bool = False` (was True)
- `log_level: str = "INFO"` (was DEBUG)

**Auth secret auto-generation (startup in `__init__.py`):**
- If `auth_secret` is still `"rkt-default-secret-change-me"`, generate random 32-byte hex
- Persist to `.env` for stability across restarts
- Log warning about auto-generated secret

**Admin PIN auto-generation (startup in `__init__.py`):**
- Replace hardcoded `"1234"` with random 6-digit PIN
- Log the PIN once on first run so user can see it
- Subsequent runs skip (admin already exists)

**Startup validation:**
- Log warnings if critical settings use defaults

### 3. File Upload Hardening (`routes_scan.py`)

In `upload_scan_image()`:
- Validate extension ∈ `{".png", ".jpg", ".jpeg", ".tiff", ".bmp"}`
- Enforce max size 100MB
- Validate MIME type starts with `image/`

### 4. Resource & Concurrency Fixes

**PIL Image leaks:**
- Add `img.close()` in `mock_scanner.py`, `wia_scanner.py`, `verification.py`

**BackgroundTaskRunner (`background.py`):**
- Replace `asyncio.Lock` with `threading.Lock` (accessed from both async and thread contexts)
- Wrap all `self.tasks` dict access with the lock

**EventBus (`events.py`):**
- Add `threading.Lock` around `_handlers` mutations

### 5. Error Handling & Logging

**Global:** Middleware handles 500 sanitization (Section 1).

**Silent except blocks:** Add `logger.debug()` to 10 silent `except: pass` blocks in:
- `routes_settings.py:818-851` (9 instances)
- `routes_dashboard.py:36` (1 instance)

**Engraving engine rollbacks:** Add `logger.exception()` before `raise` in:
- `engraving/engine.py` (4 instances)
- `security/engine.py` (1 instance)

## Files Changed

| File | Change Type |
|------|-------------|
| `app/middleware/__init__.py` | NEW — empty init |
| `app/middleware/security.py` | NEW — auth + error sanitization middleware |
| `app/api/__init__.py` | MODIFY — CORS, middleware registration, startup hardening |
| `app/config.py` | MODIFY — default debug=False, log_level=INFO |
| `app/api/routes_scan.py` | MODIFY — upload validation |
| `app/core/background.py` | MODIFY — threading.Lock |
| `app/core/events.py` | MODIFY — threading.Lock |
| `app/services/scanner/mock_scanner.py` | MODIFY — close image handles |
| `app/services/scanner/wia_scanner.py` | MODIFY — close image handles |
| `app/services/security/verification.py` | MODIFY — close image handles |
| `app/services/engraving/engine.py` | MODIFY — add logging before raise |
| `app/services/security/engine.py` | MODIFY — add logging before raise |
| `app/api/routes_settings.py` | MODIFY — add debug logging to silent excepts |
| `app/api/routes_dashboard.py` | MODIFY — add debug logging to silent except |

## Not In Scope

- Database encryption at rest (SQLCipher) — separate effort
- Per-route async wrapping of DB queries — large refactor, separate effort
- Dependency vulnerability scanning — separate CI/CD concern
- Code deduplication of query patterns — code quality, not security
