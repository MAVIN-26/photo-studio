from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT


def create_app() -> FastAPI:
    application = FastAPI(title="LumenBook")
    templates = Jinja2Templates(directory=PROJECT_ROOT / "frontend" / "templates")
    application.mount(
        "/static",
        StaticFiles(directory=PROJECT_ROOT / "frontend" / "static"),
        name="static",
    )

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(request: Request):
        return templates.TemplateResponse(request=request, name="index.html")

    @application.get("/health", tags=["health"])
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    return application


app = create_app()
