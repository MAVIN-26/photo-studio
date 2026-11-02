from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.auth.dependencies import Database, optional_user, require_admin
from app.auth.models import User
from app.rooms.models import Room

router = APIRouter(include_in_schema=False)
OptionalUser = Annotated[User | None, Depends(optional_user)]


@router.get("/", response_class=HTMLResponse)
def home(request: Request, user: OptionalUser, db: Database):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"user": user, "rooms": db.scalars(select(Room).order_by(Room.name)).all()},
    )


@router.get("/login", response_class=HTMLResponse)
@router.get("/register", response_class=HTMLResponse)
def auth_page(request: Request, user: OptionalUser):
    if user:
        return RedirectResponse("/admin" if user.role == "admin" else "/", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request=request, name="auth.html", context={"register": request.url.path == "/register"}
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: OptionalUser, db: Database):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    try:
        require_admin(user)
    except HTTPException:
        return request.app.state.templates.TemplateResponse(
            request=request, name="forbidden.html", status_code=403, context={"user": user}
        )
    rooms = db.scalars(select(Room).order_by(Room.name)).all()
    return request.app.state.templates.TemplateResponse(
        request=request, name="admin.html", context={"user": user, "rooms": rooms}
    )
