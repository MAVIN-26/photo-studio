import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.auth.router import router as auth_router
from app.config import PROJECT_ROOT, Settings, get_settings
from app.database import create_database_engine
from app.rooms.router import router as rooms_router
from app.web.formatters import format_price_minor
from app.web.router import router as web_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_database_engine(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(title="LumenBook", lifespan=lifespan)
    application.state.engine = engine
    application.state.settings = settings
    templates = Jinja2Templates(directory=PROJECT_ROOT / "frontend" / "templates")
    templates.env.filters["price"] = format_price_minor
    application.state.templates = templates
    application.mount(
        "/static",
        StaticFiles(directory=PROJECT_ROOT / "frontend" / "static"),
        name="static",
    )

    application.include_router(auth_router)
    application.include_router(rooms_router)
    application.include_router(web_router)

    @application.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path != "/static" and not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        detail = (
            error.detail
            if isinstance(error.detail, dict)
            else {"code": "HTTP_ERROR", "message": str(error.detail), "details": []}
        )
        return JSONResponse({"error": detail}, status_code=error.status_code)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        details = []
        for item in error.errors():
            field = str(item["loc"][-1]) if len(item["loc"]) > 1 else "identifier"
            if item["type"] == "value_error":
                message = item["msg"].removeprefix("Value error, ")
            elif item["type"] == "extra_forbidden":
                message = "Поле не разрешено"
            elif field == "password":
                message = (
                    "Введите пароль длиной до 128 символов"
                    if request.url.path.endswith("/login")
                    else "Пароль должен содержать от 8 до 128 символов"
                )
            elif field == "consent":
                message = "Подтвердите согласие на обработку персональных данных"
            else:
                message = "Проверьте значение поля"
            details.append({"field": field, "code": item["type"], "message": message})
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Проверьте заполнение формы.",
                    "details": details,
                }
            },
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        logger.error("Ошибка обращения к PostgreSQL: %s", type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": "Сервис временно недоступен.",
                    "details": [],
                }
            },
        )

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
