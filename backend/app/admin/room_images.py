import logging
import re
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.auth.dependencies import fail
from app.bookings.service import lock_room
from app.rooms.schemas import RoomImages

MAX_UPLOAD = 5 * 1024 * 1024
MAX_GALLERY = 5
IMAGE_FORMATS = ("JPEG", "PNG", "WEBP")
MEDIA_PREFIX = "/room-media/"
logger = logging.getLogger(__name__)


def decode_image(data: bytearray) -> bytes:
    try:
        with Image.open(BytesIO(data), formats=IMAGE_FORMATS) as source:
            if (
                source.width > 6000
                or source.height > 6000
                or source.width * source.height > 16_000_000
                or getattr(source, "is_animated", False)
            ):
                fail(422, "INVALID_IMAGE", "Выберите статичное изображение до 16 мегапикселей.")
            image = ImageOps.exif_transpose(source)
            image.thumbnail((2000, 2000))
            mode = "RGBA" if image.has_transparency_data else "RGB"
            result = BytesIO()
            image.convert(mode).save(result, format="WEBP", quality=88)
            return result.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        fail(422, "INVALID_IMAGE", "Выберите корректное изображение JPEG, PNG или WebP.")


def update_image(
    db: Session, directory: Path, room_id: UUID, position: int, version: int, data: bytes
) -> RoomImages:
    room = lock_room(db, room_id)
    if version != room.version:
        fail(409, "VERSION_CONFLICT", "Настройки зала изменились. Обновите карточку.")
    gallery = list(room.gallery_images)
    if position > len(gallery) + 1:
        fail(422, "INVALID_IMAGE_POSITION", "Сначала добавьте предыдущее изображение.")

    file_name = f"{uuid4()}.webp"
    directory.mkdir(parents=True, exist_ok=True)
    file_path = directory / file_name
    temporary = None
    try:
        with NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as target:
            temporary = Path(target.name)
            target.write(data)
        temporary.replace(file_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    new_url = MEDIA_PREFIX + file_name
    replaced = room.image_url if position == 0 else None
    if position == 0:
        room.image_url = new_url
    elif position <= len(gallery):
        replaced = gallery[position - 1]
        gallery[position - 1] = new_url
    else:
        gallery.append(new_url)
    room.gallery_images = gallery
    room.version += 1
    result = RoomImages.model_validate(room)
    # При неопределённом результате коммита файл должен остаться доступным для новой ссылки.
    db.commit()
    if replaced and re.fullmatch(r"/room-media/[0-9a-f-]{36}\.webp", replaced):
        try:
            (directory / replaced.removeprefix(MEDIA_PREFIX)).unlink(missing_ok=True)
        except OSError:
            logger.warning("Не удалось убрать предыдущий файл изображения зала")
    return result
