import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import campaigns, catalog, editor, pages
from app.errors import AppError
from app.keitaro.errors import ForbiddenCampaignError, KeitaroError
from app.services.catalog import ReferenceNotFoundError

logger = logging.getLogger(__name__)

app = FastAPI(title="Keitaro Campaign Manager")
app.include_router(catalog.router)
app.include_router(campaigns.router)
app.include_router(editor.router)
app.include_router(pages.router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")


@app.exception_handler(AppError)
def app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message, **exc.extra})


@app.exception_handler(ReferenceNotFoundError)
def reference_not_found(_: Request, exc: ReferenceNotFoundError) -> JSONResponse:
    # Misconfigured KEITARO_DOMAIN / KEITARO_GROUP / KEITARO_SOURCE
    return JSONResponse(status_code=500, content={"error": exc.message})


@app.exception_handler(ForbiddenCampaignError)
def forbidden_campaign(_: Request, exc: ForbiddenCampaignError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": exc.message})


@app.exception_handler(KeitaroError)
def keitaro_error(_: Request, exc: KeitaroError) -> JSONResponse:
    logger.warning("Keitaro error on %s: %s (%s)", exc.path, exc.message, exc.status_code)
    status_code, error = _map_keitaro_error(exc)
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "detail": exc.message, "keitaro_status": exc.status_code},
    )


def _map_keitaro_error(exc: KeitaroError) -> tuple[int, str]:
    if exc.timed_out:
        return 504, "Keitaro did not respond in time"
    match exc.status_code:
        case None:
            return 502, "Keitaro is unavailable"
        case 401:
            return 502, "Keitaro rejected the API key"
        case 402:
            return 502, "Keitaro license problem"
        case 403:
            return 502, "The API key has no access to this object in Keitaro"
        case 404:
            return 404, "Not found in Keitaro"
        case 400 | 406 | 422:
            return 422, "Keitaro rejected the data"
        case _:
            return 502, "Keitaro API error"


@app.exception_handler(Exception)
def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    # e.g. an unexpected shape of a Keitaro response
    logger.exception("Unexpected error")
    return JSONResponse(status_code=500, content={"error": "Internal error"})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
