from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "web" / "templates")

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def create_page(request: Request, settings: Settings = Depends(get_settings)):
    return templates.TemplateResponse(
        request, "create.html", {"active": "create", "prefix": settings.campaign_prefix}
    )


@router.get("/editor", response_class=HTMLResponse)
def editor_page(request: Request):
    return templates.TemplateResponse(request, "editor.html", {"active": "editor"})
