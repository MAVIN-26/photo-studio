import argparse
import getpass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.schemas import normalize_email, normalize_phone
from app.auth.service import password_hasher
from app.config import get_settings
from app.database import create_database_engine


def create_admin(db: Session, name: str, identifier: str, password: str) -> bool:
    if not name.strip() or len(name.strip()) > 100:
        raise ValueError("Имя должно содержать от 1 до 100 символов")
    email = normalize_email(identifier) if "@" in identifier else None
    phone = None if email else normalize_phone(identifier)
    existing = db.scalar(select(User).where(User.email == email if email else User.phone == phone))
    if existing:
        if existing.role != "admin":
            raise ValueError("Контакт уже принадлежит клиенту; его роль не изменена")
        return False
    if not 8 <= len(password) <= 128:
        raise ValueError("Пароль должен содержать от 8 до 128 символов")
    db.add(
        User(
            name=name.strip(),
            email=email,
            phone=phone,
            role="admin",
            password_hash=password_hasher.hash(password),
        )
    )
    db.flush()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Создание администратора LumenBook")
    parser.add_argument("--name", required=True)
    parser.add_argument("--identifier", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Пароль: ")
    if password != getpass.getpass("Повторите пароль: "):
        parser.error("Пароли не совпадают")
    engine = create_database_engine(get_settings())
    try:
        with Session(engine) as db, db.begin():
            created = create_admin(db, args.name, args.identifier, password)
        print(
            "Администратор создан." if created else "Администратор уже существует; пароль сохранён."
        )
    except (ValueError, IntegrityError) as error:
        parser.exit(
            1, f"Ошибка: {error if isinstance(error, ValueError) else 'Контакт уже занят'}\n"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
