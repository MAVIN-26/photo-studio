from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine, expire_on_commit=False) as db:
        yield db


Database = Annotated[Session, Depends(get_db)]
