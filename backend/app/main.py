import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import PROJECT_ROOT, Settings, get_settings
from app.database import create_database_engine

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    engine = create_database_engine(settings or get_settings())

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(title="LumenBook", lifespan=lifespan)
    application.state.engine = engine
    templates = Jinja2Templates(directory=PROJECT_ROOT / "frontend" / "templates")
    application.mount(
        "/static",
        StaticFiles(directory=PROJECT_ROOT / "frontend" / "static"),
        name="static",
    )

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(request: Request):
        return templates.TemplateResponse(request=request, name="index.html")

    @application.get("/health", tags=["health"], responses={503: {"description": "БД недоступна"}})
    def health(request: Request) -> JSONResponse:
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            logger.exception("Ошибка проверки подключения к PostgreSQL")
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "SERVICE_UNAVAILABLE",
                        "message": "База данных недоступна.",
                        "details": [],
                    }
                },
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            {"status": "ok", "database": "ok"},
            headers={"Cache-Control": "no-store"},
        )

    return application


app = create_app()
