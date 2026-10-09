from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


class Message(BaseModel):
    message: str


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    email: str | None = Field(default=None, max_length=160)


class IdName(ORM):
    id: uuid.UUID
    name: str


__all__ = ["ORM", "Page", "Message", "CustomerIn", "IdName", "uuid", "date", "datetime", "Decimal"]
