import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.infrastructure.db.session import init_db
from app.infrastructure.logging import configure_logging
from app.infrastructure.settings import get_settings
from app.interfaces.api.middleware import request_context_middleware
from app.interfaces.api.routes import auth_routes, document_routes, health_routes, qa_routes, voice_routes, wiki_routes, workspace_routes
from app.shared.request_context import get_request_id

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(request_context_middleware)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"message": exc.detail, "code": exc.status_code, "request_id": get_request_id()}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"message": "Validation failed", "code": 422, "request_id": get_request_id(), "details": exc.errors()}},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error")
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "code": 500, "request_id": get_request_id()}},
        )

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    app.include_router(health_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(workspace_routes.router)
    app.include_router(document_routes.router)
    app.include_router(wiki_routes.router)
    app.include_router(qa_routes.router)
    app.include_router(voice_routes.router)
    return app


app = create_app()
