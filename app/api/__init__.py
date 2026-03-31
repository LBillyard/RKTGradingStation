"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

UI_DIR = Path(__file__).parent.parent / "ui"


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


def _create_lifespan(app_settings):
    """Create the lifespan context manager with access to settings."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ===================== STARTUP =====================
        import os
        import secrets
        from app.core.logging_config import setup_logging

        setup_logging(app_settings.log_level, Path(app_settings.data_dir))
        logger.info("Starting RKT Grading Station v1.0.0")

        # Agent mode: skip database init, operator seeding, and webhook subscriptions
        if app_settings.mode == "agent":
            logger.info("Agent mode — skipping desktop/cloud initialization")
            yield
            return

        from app.db.database import init_db

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

        # --- Migrate pin_hash -> password_hash if needed ---
        from app.db.database import get_session
        from app.models.operator import Operator
        _seed_db = get_session()
        try:
            from sqlalchemy import text, inspect as sa_inspect
            _engine = _seed_db.get_bind()
            inspector = sa_inspect(_engine)
            columns = [c['name'] for c in inspector.get_columns('operators')]
            if 'pin_hash' in columns and 'password_hash' not in columns:
                _seed_db.execute(text('ALTER TABLE operators RENAME COLUMN pin_hash TO password_hash'))
                _seed_db.commit()
                logger.info("Migrated operators.pin_hash -> password_hash")

            # --- Seed default admin (only if NO operators exist) ---
            any_operator = _seed_db.query(Operator).first()
            if not any_operator:
                import bcrypt
                default_pw = os.environ.get("RKT_DEFAULT_ADMIN_PASSWORD", "ChangeMe123!")
                pw_hash = bcrypt.hashpw(default_pw.encode(), bcrypt.gensalt()).decode()
                admin = Operator(
                    name="admin",
                    password_hash=pw_hash,
                    role="admin",
                    # TODO(H2): Operator model needs a `must_change_password` Boolean column.
                    # Once added, set must_change_password=True here so the frontend
                    # forces a password change on first login with the default credentials.
                )
                _seed_db.add(admin)
                _seed_db.commit()
                logger.warning("Default admin created — change the password immediately via Admin panel")
        finally:
            _seed_db.close()

        # Subscribe webhooks to the event bus
        from app.core.events import event_bus, Events
        from app.services.webhook import fire_webhook_background

        event_bus.subscribe(Events.GRADE_APPROVED, lambda d: fire_webhook_background("grade.approved", d))
        event_bus.subscribe(Events.GRADE_OVERRIDDEN, lambda d: fire_webhook_background("grade.overridden", d))
        event_bus.subscribe(Events.AUTH_FLAGGED, lambda d: fire_webhook_background("auth.flagged", d))
        logger.info("Webhook event subscriptions registered")

        # Auto-link AI grades to training data
        def _on_grade_calculated(data):
            if not data or "card_record_id" not in data:
                return
            try:
                from app.services.training.service import link_ai_grade
                _link_db = get_session()
                try:
                    link_ai_grade(data["card_record_id"], _link_db)
                finally:
                    _link_db.close()
            except Exception as e:
                logger.debug(f"Training link skipped: {e}")

        event_bus.subscribe(Events.GRADE_CALCULATED, _on_grade_calculated)

        yield  # =============== APP IS RUNNING ===============

        # ===================== SHUTDOWN =====================
        logger.info("Shutting down RKT Grading Station...")

        # Close database connections
        from app.db.database import _engine as db_engine
        if db_engine is not None:
            db_engine.dispose()
            logger.info("Database connections closed")

        # Clean temp files
        import shutil
        temp_dir = Path(app_settings.data_dir) / "temp"
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info("Temp directory cleaned up")

        logger.info("Shutdown complete")

    return lifespan


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from app.config import settings

    app = FastAPI(
        title="RKT Grading Station",
        version="1.0.0",
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
        lifespan=_create_lifespan(settings),
    )

    # CORS — mode-aware origins
    cors_origins = [
        f"http://127.0.0.1:{settings.server_port}",
        f"http://localhost:{settings.server_port}",
    ]
    if settings.mode == "cloud":
        # Allow browser to talk to local agent
        cors_origins.append("http://localhost:8742")
        cors_origins.append("http://127.0.0.1:8742")
        # Allow SSO redirects from RKT admin dashboard
        cors_origins.append("https://rktgrading.com")
    elif settings.mode == "agent":
        # Agent accepts requests from the cloud UI and localhost
        cors_origins = [
            "https://rgs.rktgrading.com",
            "http://localhost:8741",
            "http://127.0.0.1:8741",
        ]

    # M3: Restrict CORS methods and headers to explicit allow-lists
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )

    # Security middleware — auth enforcement + error sanitization
    from app.middleware.security import SecurityMiddleware
    app.add_middleware(SecurityMiddleware, debug=settings.debug)

    # Mount static files
    static_dir = UI_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # H4: Authenticated endpoint for data files instead of unauthenticated StaticFiles mount
    from app.config import settings as app_settings
    if settings.mode != "agent":
        _data_dir = Path(app_settings.data_dir).resolve()

        @app.get("/data/{file_path:path}")
        async def serve_data_file(file_path: str):
            """Serve files from the data directory with auth (enforced by SecurityMiddleware)
            and path traversal protection."""
            # Resolve the requested path and ensure it stays within data_dir
            requested = (_data_dir / file_path).resolve()
            if not str(requested).startswith(str(_data_dir)):
                raise HTTPException(status_code=403, detail="Access denied")
            if not requested.is_file():
                raise HTTPException(status_code=404, detail="File not found")
            return FileResponse(str(requested))

    # Register API routers based on mode
    # Cloud + Desktop: all analysis/data/UI routes
    if settings.mode in ("desktop", "cloud"):
        from app.api.routes_dashboard import router as dashboard_router
        from app.api.routes_scan import router as scan_router
        from app.api.routes_queue import router as queue_router
        from app.api.routes_grading import router as grading_router
        from app.api.routes_authenticity import router as authenticity_router
        from app.api.routes_security import router as security_router
        from app.api.routes_reference import router as reference_router
        from app.api.routes_reports import router as reports_router
        from app.api.routes_settings import router as settings_router
        from app.api.routes_audit import router as audit_router
        from app.api.routes_backup import router as backup_router
        from app.api.routes_auth import router as auth_router
        from app.api.routes_pdf import router as pdf_router
        from app.api.routes_slab import router as slab_router

        app.include_router(dashboard_router, prefix="/api/dashboard", tags=["Dashboard"])
        app.include_router(scan_router, prefix="/api/scan", tags=["Scanning"])
        app.include_router(queue_router, prefix="/api/queue", tags=["Queue"])
        app.include_router(grading_router, prefix="/api/grading", tags=["Grading"])
        app.include_router(authenticity_router, prefix="/api/authenticity", tags=["Authenticity"])
        app.include_router(security_router, prefix="/api/security", tags=["Security"])
        app.include_router(reference_router, prefix="/api/reference", tags=["Reference Library"])
        app.include_router(reports_router, prefix="/api/reports", tags=["Reports"])
        app.include_router(settings_router, prefix="/api/settings", tags=["Settings"])
        app.include_router(audit_router, prefix="/api/audit", tags=["Audit"])
        app.include_router(backup_router, prefix="/api/backup", tags=["Backup"])
        app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
        app.include_router(pdf_router, prefix="/api/reports", tags=["Reports"])
        app.include_router(slab_router, prefix="/api/slab", tags=["Slab Assembly"])

        from app.api.routes_analytics import router as analytics_router
        app.include_router(analytics_router, prefix="/api/analytics", tags=["Analytics"])

        from app.api.routes_training import router as training_router
        app.include_router(training_router, prefix="/api/training", tags=["Training"])

        from app.api.routes_enhancements import router as enhancements_router
        app.include_router(enhancements_router, prefix="/api/enhancements", tags=["Enhancements"])

    # Agent + Desktop: hardware routes (scanner, printer, NFC)
    if settings.mode in ("desktop", "agent"):
        from app.api.routes_agent_hw import router as agent_hw_router
        app.include_router(agent_hw_router, prefix="/agent", tags=["Agent Hardware"])

    logger.info(f"App mode: {settings.mode} — registered routes accordingly")

    # Agent version and download endpoints (served by cloud)
    _AGENT_LATEST = "1.4.0"

    if settings.mode in ("desktop", "cloud"):
        @app.get("/api/agent/version")
        async def agent_latest_version():
            return {
                "latest_version": _AGENT_LATEST,
                "download_url": "https://rktgradingstation.co.uk/api/agent/download",
                "release_notes": "Telemetry, scanner quality monitoring, image tamper detection, chain of custody, analytics",
                "mandatory": False,
            }

        @app.get("/api/agent/download")
        async def agent_download():
            """Generate a presigned S3 URL and redirect to download the agent."""
            from fastapi.responses import RedirectResponse
            try:
                import boto3
                from botocore.config import Config
                region = app_settings.s3.region or "eu-west-2"
                # Use explicit creds if set, otherwise fall back to IAM instance role
                kwargs = {
                    "region_name": region,
                    "endpoint_url": f"https://s3.{region}.amazonaws.com",
                    "config": Config(s3={"addressing_style": "virtual"}),
                }
                if app_settings.s3.access_key_id and app_settings.s3.secret_access_key:
                    kwargs["aws_access_key_id"] = app_settings.s3.access_key_id
                    kwargs["aws_secret_access_key"] = app_settings.s3.secret_access_key
                s3 = boto3.client("s3", **kwargs)
                url = s3.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": app_settings.s3.bucket or "rkt-grading-images",
                        "Key": "downloads/RKTStationAgent-latest.exe",
                        "ResponseContentDisposition": f"attachment; filename=RKTStationAgent-v{_AGENT_LATEST}.exe",
                    },
                    ExpiresIn=3600,
                )
                return RedirectResponse(url)
            except Exception as e:
                logger.error(f"Agent download failed: {e}")
                return JSONResponse({"error": "Agent download not available"}, status_code=404)

        @app.get("/api/agent/changelog")
        async def agent_changelog():
            """Return the agent changelog."""
            import json
            changelog_path = Path(__file__).parent.parent.parent / "agent_changelog.json"
            if changelog_path.exists():
                return json.loads(changelog_path.read_text(encoding="utf-8"))
            return []

    # Robots.txt — block all search engine indexing
    @app.get("/robots.txt")
    async def robots_txt():
        return FileResponse(str(UI_DIR / "static" / "robots.txt"), media_type="text/plain")

    # SPA catch-all: serve index.html for non-API, non-static routes
    @app.get("/")
    async def serve_index():
        return FileResponse(str(UI_DIR / "index.html"))

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        # Don't catch API or static routes
        if path.startswith(("api/", "static/", "data/")):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return FileResponse(str(UI_DIR / "index.html"))

    return app
