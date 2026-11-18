from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.admin import room_images, service
from app.admin.schemas import (
    AdminBooking,
    AdminBookingFilters,
    AdminSchedule,
    ChangedAdminBooking,
    CreateBlock,
    CreateManualBooking,
    RoomSettingsPatch,
    ScheduleBlock,
)
from app.auth.dependencies import CsrfSession, fail, require_admin
from app.auth.models import User
from app.bookings.schemas import Availability, BookingList, BookingVersion, RescheduleBooking
from app.dependencies import Database
from app.rooms.schemas import RoomImages, RoomResponse
from app.rooms.service import get_room

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])
Admin = Annotated[User, Depends(require_admin)]


@router.post("/blocks", status_code=201, response_model=ScheduleBlock)
def create_block(
    body: CreateBlock, admin: Admin, db: Database, csrf: CsrfSession, response: Response
):
    entry = service.create_block(db, admin.id, body)
    response.headers["Location"] = f"/api/v1/admin/blocks/{entry.id}"
    return service.block_response(entry)


@router.get("/blocks/{block_id}", response_model=ScheduleBlock)
def block_detail(block_id: UUID, db: Database):
    return service.block_response(service.read_block(db, block_id))


@router.post("/blocks/{block_id}/cancel", response_model=ScheduleBlock)
def cancel_block(
    block_id: UUID, body: BookingVersion, admin: Admin, db: Database, csrf: CsrfSession
):
    return service.block_response(service.cancel_block(db, admin.id, block_id, body.version))


@router.patch("/rooms/{room_id}", response_model=RoomResponse)
def update_room(
    room_id: UUID, body: RoomSettingsPatch, admin: Admin, db: Database, csrf: CsrfSession
):
    return service.update_room_settings(db, room_id, body, admin.id)


@router.get("/rooms/{room_id}/images", response_model=RoomImages)
def get_room_images(room_id: UUID, db: Database):
    room = get_room(db, room_id)
    if room is None:
        fail(404, "ROOM_NOT_FOUND", "Зал не найден.")
    return room


@router.put("/rooms/{room_id}/images/{position}", response_model=RoomImages)
async def upload_room_image(
    room_id: UUID,
    position: Annotated[int, Path(ge=0, le=room_images.MAX_GALLERY)],
    version: Annotated[int, Query(ge=1)],
    request: Request,
    db: Database,
    csrf: CsrfSession,
):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > room_images.MAX_UPLOAD:
            fail(413, "IMAGE_TOO_LARGE", "Изображение должно весить не больше 5 МБ.")
        data.extend(chunk)
    image = await run_in_threadpool(room_images.decode_image, data)
    return await run_in_threadpool(
        room_images.update_image, db, request.app.state.settings.room_media_dir,
        room_id, position, version, image,
    )


@router.get("/schedule", response_model=AdminSchedule)
def schedule(date_from: date, date_to: date, db: Database, room_id: UUID | None = None):
    return service.read_schedule(db, date_from, date_to, room_id)


@router.get("/bookings", response_model=BookingList)
def booking_list(filters: Annotated[AdminBookingFilters, Query()], db: Database) -> BookingList:
    return service.list_admin_bookings(db, filters)


@router.get("/bookings/{booking_id}", response_model=AdminBooking)
def booking_detail(booking_id: UUID, db: Database):
    return service.admin_booking_response(db, service.read_booking(db, booking_id))


@router.post("/bookings", status_code=201, response_model=ChangedAdminBooking)
def create(
    body: CreateManualBooking, admin: Admin, db: Database, csrf: CsrfSession, response: Response
):
    entry = service.create_manual_booking(db, admin.id, body)
    response.headers["Location"] = f"/api/v1/admin/bookings/{entry.id}"
    return ChangedAdminBooking(
        **service.admin_booking_response(db, entry).model_dump(), message="Бронь создана."
    )


@router.get("/bookings/{booking_id}/availability", response_model=Availability)
def booking_availability(booking_id: UUID, date: date, db: Database):
    return service.reschedule_availability(db, booking_id, date)


@router.post("/bookings/{booking_id}/confirm", response_model=ChangedAdminBooking)
def confirm(booking_id: UUID, body: BookingVersion, admin: Admin, db: Database, csrf: CsrfSession):
    entry = service.confirm_booking(db, booking_id, body.version, admin.id)
    return ChangedAdminBooking(
        **service.admin_booking_response(db, entry).model_dump(), message="Бронь подтверждена."
    )


@router.post("/bookings/{booking_id}/cancel", response_model=ChangedAdminBooking)
def cancel(booking_id: UUID, body: BookingVersion, admin: Admin, db: Database, csrf: CsrfSession):
    entry = service.cancel_booking(db, booking_id, body.version, admin.id)
    return ChangedAdminBooking(
        **service.admin_booking_response(db, entry).model_dump(), message="Бронь отменена."
    )


@router.post("/bookings/{booking_id}/reschedule", response_model=ChangedAdminBooking)
def reschedule(
    booking_id: UUID, body: RescheduleBooking, admin: Admin, db: Database, csrf: CsrfSession
):
    entry = service.reschedule_booking(db, booking_id, body, admin.id)
    return ChangedAdminBooking(
        **service.admin_booking_response(db, entry).model_dump(), message="Бронь перенесена."
    )
