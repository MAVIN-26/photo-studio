from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.dependencies import Database
from app.rooms.schemas import RoomListResponse, RoomResponse
from app.rooms.service import get_room, list_rooms

router = APIRouter(prefix="/api/v1/rooms", tags=["rooms"])


@router.get("", response_model=RoomListResponse)
def room_list(db: Database):
    return {"items": list_rooms(db)}


@router.get("/{room_id}", response_model=RoomResponse)
def room_detail(room_id: UUID, db: Database):
    room = get_room(db, room_id)
    if room is None:
        raise HTTPException(
            404,
            detail={"code": "ROOM_NOT_FOUND", "message": "Зал не найден.", "details": []},
        )
    return room
