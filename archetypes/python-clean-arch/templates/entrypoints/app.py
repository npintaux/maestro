"""FastAPI HTTP entrypoint adapter mapping OpenAPI routes to domain services."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

# Create the standard FastAPI application
app = FastAPI(
    title="Maestro Clean Architecture Microservice",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)


@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["System"])
def health_check() -> dict[str, str]:
    """Liveness and readiness probe endpoint for Kubernetes / Cloud Run.

    Returns:
        JSON response with healthy status.
    """
    return {"status": "ok", "service": "subsystem-clean-arch"}


@app.exception_handler(Exception)
async def generic_exception_handler(request: Any, exc: Exception) -> JSONResponse:
    """Fallback exception handler ensuring structured 500 error responses.

    Args:
        request: The incoming HTTP request.
        exc: The unhandled exception.

    Returns:
        Structured JSON response with status 500.
    """
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error occurred.", "error_type": type(exc).__name__},
    )
