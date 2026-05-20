"""
This module defines type aliases for database models/sessions/.... used in the application.
This means: In the application, you normaly never refer to the original types from SQLModel or Sqlalchemy or ...
"""

from typing import Optional, Type

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, aliased, sessionmaker
from sqlalchemy.sql import Select
from typing_extensions import TypeAlias
