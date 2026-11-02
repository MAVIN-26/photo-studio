import re
from typing import Self
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


def normalize_email(value: str) -> str:
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as error:
        raise ValueError("Введите корректный email") from error


def normalize_phone(value: str) -> str:
    value = re.sub(r"[\s()\-]", "", value)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
        raise ValueError(
            "Введите телефон полностью в международном формате, например +7 999 000-00-01"
        )
    return value


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    consent: StrictBool

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Введите имя")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return normalize_email(value) if value is not None else None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return normalize_phone(value) if value is not None else None

    @field_validator("consent")
    @classmethod
    def validate_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "Без согласия на обработку персональных данных зарегистрироваться нельзя"
            )
        return value

    @model_validator(mode="after")
    def require_contact(self) -> Self:
        if not self.email and not self.phone:
            raise ValueError("Введите телефон или email")
        return self


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    email: str | None
    phone: str | None
    role: str


class AuthResponse(BaseModel):
    user: UserResponse
    csrf_token: str
    redirect_url: str
