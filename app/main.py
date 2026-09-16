import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.logging_config import configure_logging, get_logger, request_id_var
from app.models import User
from app.routers import auth, download, files
from app.security import hash_password
from app.storage import storage_root

configure_logging(settings.is_development)
log = get_logger("app.main")

# Demo fixtures for local development only. Seeding is gated on ENVIRONMENT
# below, so these accounts are never created in production.
SEED_USERS = [
    ("alice", os.getenv("SEED_PASSWORD_ALICE", "alice-password")),
    ("bob", os.getenv("SEED_PASSWORD_BOB", "bob-password")),
]


def seed_users() -> None:
    db = SessionLocal()
    try:
        for username, password in SEED_USERS:
            exists = db.query(User).filter(User.username == username).first()
            if exists is None:
                db.add(User(username=username, password_hash=hash_password(password)))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    if settings.is_development:
        seed_users()
        log.warning(
            "demo_users_seeded",
            usernames=[u for u, _ in SEED_USERS],
            note="development only — not created in other environments",
        )

    root = storage_root()
    log.info(
        "service_startup",
        environment=settings.environment,
        storage_root=str(root),
    )
    yield
    log.info("service_shutdown")


app = FastAPI(
    title="Secure File Sharing Service",
    description=(
        "Upload private files and generate time-limited, cryptographically "
        "signed download links."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID")
    request_id = incoming or uuid.uuid4().hex
    token = request_id_var.set(request_id)
    try:
        log.info("request_started", method=request.method, path=request.url.path)
        response = await call_next(request)
        log.info("request_finished", status_code=response.status_code)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_var.reset(token)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code >= 500:
        log.error("server_error", status_code=exc.status_code, detail=str(exc.detail))
    else:
        log.warning("client_error", status_code=exc.status_code, detail=str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": request_id_var.get()},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    log.warning("validation_error", errors=exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Request validation failed",
            "errors": [
                {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                for e in exc.errors()
            ],
            "request_id": request_id_var.get(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "request_id": request_id_var.get(),
        },
    )


app.include_router(auth.router)
app.include_router(files.router)
app.include_router(download.router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "environment": settings.environment}
