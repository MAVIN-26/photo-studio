from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.auth.dependencies import optional_user, require_admin
from app.auth.models import User
from app.bookings import service
from app.bookings.service import HOUR, allowed_actions, list_bookings, owned_booking
from app.dependencies import Database
from app.rooms.models import Room
from app.rooms.service import get_room, list_rooms

router = APIRouter(include_in_schema=False)
OptionalUser = Annotated[User | None, Depends(optional_user)]


@router.get("/", response_class=HTMLResponse)
def home(request: Request, user: OptionalUser, db: Database):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"user": user, "rooms": list_rooms(db)},
    )


@router.get("/rooms/{room_id}", response_class=HTMLResponse)
def room_page(room_id: str, request: Request, user: OptionalUser, db: Database):
    try:
        room_uuid = UUID(room_id)
    except ValueError:
        room = None
    else:
        room = get_room(db, room_uuid)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="room.html" if room else "room_not_found.html",
        status_code=200 if room else 404,
        context={"user": user, "room": room, "today": service.studio_now().date()},
    )


@router.get("/login", response_class=HTMLResponse)
@router.get("/register", response_class=HTMLResponse)
def auth_page(request: Request, user: OptionalUser, room: str | None = None):
    try:
        room_id = UUID(room) if room else None
    except ValueError:
        room_id = None
    booking_return = f"/rooms/{room_id}#booking" if room_id else None
    if user:
        target = "/admin" if user.role == "admin" else booking_return or "/"
        return RedirectResponse(target, status_code=303)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="auth.html",
        context={
            "register": request.url.path == "/register",
            "booking_return": booking_return,
            "auth_query": f"?room={room_id}" if room_id else "",
        },
    )


@router.get("/my/bookings", response_class=HTMLResponse)
def my_bookings(
    request: Request,
    user: OptionalUser,
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.role != "client":
        return RedirectResponse("/admin", status_code=303)
    items, total = list_bookings(db, user.id, scope="all", status=None, limit=20, offset=offset)
    rooms = {room.id: room.name for room in list_rooms(db)}
    now = service.studio_now()
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="my_bookings.html",
        context={
            "user": user,
            "items": items,
            "rooms": rooms,
            "offset": offset,
            "total": total,
            "actions": {entry.id: allowed_actions(entry, now) for entry in items},
        },
    )


@router.get("/my/bookings/{booking_id}", response_class=HTMLResponse)
def my_booking(booking_id: UUID, request: Request, user: OptionalUser, db: Database):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    entry = owned_booking(db, user.id, booking_id) if user.role == "client" else None
    room = get_room(db, entry.room_id) if entry else None
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="my_booking.html",
        status_code=200 if entry else 404,
        context={
            "user": user,
            "entry": entry,
            "room": room,
            "actions": {entry.id: allowed_actions(entry, service.studio_now())} if entry else {},
        },
    )


@router.get("/my/bookings/{booking_id}/reschedule", response_class=HTMLResponse)
def reschedule_page(booking_id: UUID, request: Request, user: OptionalUser, db: Database):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    entry = owned_booking(db, user.id, booking_id) if user.role == "client" else None
    if entry is None:
        return request.app.state.templates.TemplateResponse(
            request=request,
            name="my_booking.html",
            status_code=404,
            context={"user": user, "entry": None},
        )
    now = service.studio_now()
    if "reschedule" not in allowed_actions(entry, now):
        return RedirectResponse(f"/my/bookings/{booking_id}", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="reschedule.html",
        context={
            "user": user,
            "entry": entry,
            "room": get_room(db, entry.room_id),
            "today": now.date(),
            "duration_hours": (entry.ends_at - entry.starts_at) // HOUR,
        },
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
