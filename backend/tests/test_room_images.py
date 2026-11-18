from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from scripts.create_admin import create_admin
from scripts.seed_rooms import seed_rooms

PASSWORD = "Demo-password-123"


def test_room_image_upload_permissions_validation_and_gallery(database, tmp_path):
    from app.main import create_app

    engine, settings, _ = database
    seed_rooms(engine)
    settings.room_media_dir = tmp_path
    with Session(engine) as db, db.begin():
        create_admin(db, "Администратор", "images-admin@example.ru", PASSWORD)

    with TestClient(create_app(settings)) as admin, TestClient(create_app(settings)) as visitor:
        room = visitor.get("/api/v1/rooms").json()["items"][0]
        url = f"/api/v1/admin/rooms/{room['id']}/images"
        destination = f"{url}/0?version=1"
        image = BytesIO()
        Image.new("RGB", (20, 15), "purple").save(image, "PNG")
        contents = image.getvalue()
        assert visitor.put(destination, content=contents).status_code == 401
        token = admin.get("/api/v1/auth/csrf").json()["csrf_token"]
        login = admin.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": token},
            json={"identifier": "images-admin@example.ru", "password": PASSWORD},
        )
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        assert admin.put(destination, content=contents).status_code == 403
        assert admin.put(destination, headers=headers, content=b"invalid").status_code == 422
        assert not list(tmp_path.iterdir())
        cover = admin.put(destination, headers=headers, content=contents).json()
        assert cover["version"] == 2
        assert cover["gallery_images"] == []
        assert admin.put(destination, headers=headers, content=contents).status_code == 409

        gallery = admin.put(f"{url}/1?version=2", headers=headers, content=contents).json()
        picture = gallery["gallery_images"][0]
        assert gallery["version"] == 3
        assert gallery["image_url"] == cover["image_url"]
        for image_url in (cover["image_url"], picture):
            response = visitor.get(image_url)
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/webp"
        assert picture in visitor.get(f"/rooms/{room['id']}").text

        replaced = admin.put(f"{url}/0?version=3", headers=headers, content=contents).json()
        assert replaced["gallery_images"] == [picture]
        assert visitor.get(cover["image_url"]).status_code == 404
        assert visitor.get(replaced["image_url"]).status_code == 200
