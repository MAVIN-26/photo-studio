from datetime import date, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.admin.service import read_schedule
from app.auth.dependencies import fail, optional_user
from app.auth.models import User
from app.bookings import service
from app.bookings.service import HOUR, allowed_actions, booking_tabs, owned_booking
from app.dependencies import Database
from app.rooms.service import get_room, list_rooms
from app.web.schedule import FIRST_HOUR, LAST_HOUR, date_label, schedule_columns, short_date

router = APIRouter(include_in_schema=False)
OptionalUser = Annotated[User | None, Depends(optional_user)]


@router.get("/", response_class=HTMLResponse)
def home(request: Request, user: OptionalUser, db: Database):
    rooms = list_rooms(db)
    now = service.studio_now()
    schedules = service.daily_availability(db, rooms, now.date(), now)
    free_hours = {
        room_id: [slot.starts_at.strftime("%H:%M") for slot in schedule.slots if slot.available]
        for room_id, schedule in schedules.items()
    }
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "rooms": rooms,
            "free_hours": free_hours,
            "date": short_date(now.date()),
        },
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
def auth_page(
    request: Request,
    user: OptionalUser,
    room: str | None = None,
    next_page: Annotated[str | None, Query(alias="next")] = None,
):
    try:
        room_id = UUID(room) if room else None
    except ValueError:
        room_id = None
    booking_return = f"/rooms/{room_id}#booking" if room_id else None
    auth_query = f"?room={room_id}" if room_id else ""
    if next_page == "bookings":
        booking_return, auth_query = "/my/bookings", "?next=bookings"
    if user:
        target = "/admin" if user.role == "admin" else booking_return or "/"
        return RedirectResponse(target, status_code=303)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="auth.html",
        context={
            "register": request.url.path == "/register",
            "booking_return": booking_return,
            "auth_query": auth_query,
        },
    )


@router.get("/my/bookings", response_class=HTMLResponse)
def my_bookings(
    request: Request,
    user: OptionalUser,
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    tab: Literal["upcoming", "past"] = "upcoming",
):
    if user is None:
        return RedirectResponse("/login?next=bookings", status_code=303)
    if user.role != "client":
        return RedirectResponse("/admin", status_code=303)
    now = service.studio_now()
    items, counts = booking_tabs(db, user.id, now, tab, 20, offset)
    if offset and offset >= counts[tab]:
        return RedirectResponse(f"/my/bookings?tab={tab}", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="my_bookings.html",
        context={
            "user": user,
            "items": items,
            "rooms": {room.id: room for room in list_rooms(db)},
            "tab": tab,
            "counts": counts,
            "now": now,
            "offset": offset,
            "total": counts[tab],
            "studio_phone": request.app.state.settings.studio_phone,
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
            "notification": service.latest_booking_notification(db, entry) if entry else None,
            "duration_hours": (entry.ends_at - entry.starts_at) // HOUR if entry else None,
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


@router.get("/demo", response_class=HTMLResponse)
def demo_page(request: Request, user: OptionalUser, db: Database):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="demo.html",
        context={"user": user, "rooms": {room.name: room for room in list_rooms(db)}},
    )


@router.get("/room-media/{image_id}.webp")
def room_image(image_id: UUID, request: Request):
    path = request.app.state.settings.room_media_dir / f"{image_id}.webp"
    if not path.is_file():
        fail(404, "IMAGE_NOT_FOUND", "Изображение не найдено.")
    return FileResponse(
        path, media_type="image/webp", headers={"X-Content-Type-Options": "nosniff"}
    )


def admin_page_denial(request: Request, user: User | None):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.role != "admin":
        return request.app.state.templates.TemplateResponse(
            request=request, name="forbidden.html", status_code=403, context={"user": user}
        )
    return None


@router.get("/admin/rooms", response_class=HTMLResponse)
def admin_room_settings(request: Request, user: OptionalUser, db: Database):
    denial = admin_page_denial(request, user)
    if denial is not None:
        return denial
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="admin_room_settings.html",
        context={
            "user": user,
            "rooms": list_rooms(db),
            "hours": range(FIRST_HOUR, LAST_HOUR + 1),
        },
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    user: OptionalUser,
    db: Database,
    selected_date: Annotated[date | None, Query(alias="date")] = None,
):
    denial = admin_page_denial(request, user)
    if denial is not None:
        return denial
    today = service.studio_now().date()
    day = selected_date or today
    schedule = read_schedule(db, day, day)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "user": user,
            "schedule": schedule,
            "day": day,
            "today": today,
            "last_booking_day": today + service.BOOKING_HORIZON,
            "date_label": date_label(day),
            "hours": range(FIRST_HOUR, LAST_HOUR),
            "previous": day - timedelta(days=1) if day.toordinal() > 1 else None,
            "next": day + timedelta(days=1) if day < date.max - timedelta(days=1) else None,
            "columns": schedule_columns(schedule),
        },
    )
