"""FastAPI application entry point.

Run from the backend/ folder:  uvicorn app.main:app --reload --port 8000
From the project root:         uvicorn app.main:app --app-dir backend --reload --port 8000

backend/.env is loaded automatically at import (see config.load_env_file).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, config, database, seed
from .errors import AppError, error_body
from .routers import dashboard, identities, incidents, scenarios

logger = logging.getLogger("trustbreak")

# Load backend/.env before anything reads configuration (path is independent of the cwd).
config.load_env_file()

_HTTP_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()
    if config.seed_enabled():
        conn = database.connect()
        try:
            seed.seed_if_empty(conn)
        finally:
            conn.close()
    yield


def _validation_details(exc: RequestValidationError) -> list[dict]:
    details = []
    for error in exc.errors():
        if error.get("type") == "json_invalid":
            field, message = "_form", "Request body is not valid JSON."
        else:
            field = ".".join(str(part) for part in error["loc"][1:]) or "_form"
            message = str(error.get("msg", "Invalid value")).removeprefix("Value error, ")
        details.append({"field": field, "message": message})
    return details


def create_app() -> FastAPI:
    app = FastAPI(title="TrustBreak API", version=__version__, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.get_cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "Some fields are invalid.", _validation_details(exc)),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException):
        code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code, content=error_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Something went wrong on the server."),
        )

    app.include_router(incidents.router)
    app.include_router(identities.router)
    app.include_router(scenarios.router)
    app.include_router(dashboard.router)

    @app.get("/api/health", tags=["system"])
    def health():
        return {"success": True, "data": {"status": "ok", "service": "trustbreak-api", "version": app.version}}

    return app


app = create_app()
