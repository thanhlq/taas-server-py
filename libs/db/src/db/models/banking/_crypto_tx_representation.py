from __future__ import annotations

from decimal import Decimal
from typing import Optional

from advanced_alchemy.base import UUIDv7AuditBase
from sqlalchemy import (
    TEXT,
    ForeignKey,
    Integer,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column

from .contants import CRYPTO_TOKEN_TABLE, CRYPTO_TRANSACTION_PRESENTATION_TABLE


class CryptoTransactionRepresentationOrm(UUIDv7AuditBase):
    __tablename__ = CRYPTO_TRANSACTION_PRESENTATION_TABLE

    user_uuid: Mapped[str] = mapped_column(TEXT, nullable=False)
    type: Mapped[str] = mapped_column(TEXT, nullable=False)
    from_address: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    to_address: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    status: Mapped[str] = mapped_column(TEXT, nullable=False)
    blockchain: Mapped[str] = mapped_column(TEXT, nullable=False)
    network: Mapped[str] = mapped_column(TEXT, nullable=False)
    token: Mapped[str] = mapped_column(TEXT, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    network_fee: Mapped[Optional[Decimal]] = mapped_column(
        Numeric, default=None, nullable=True
    )
    platform_fee: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    hash: Mapped[Optional[str]] = mapped_column(TEXT, default=None, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(TEXT, default=None, nullable=True)
    platform_fee_uuid: Mapped[Optional[str]] = mapped_column(
        TEXT, default=None, nullable=True, index=True
    )
    platform_fee_token_uuid: Mapped[Optional[str]] = mapped_column(
        'platform_fee_token',
        TEXT,
        ForeignKey(f'{CRYPTO_TOKEN_TABLE}.uuid'),
        default=None,
        nullable=True,
        index=True,
    )
    fiat: Mapped[Optional[str]] = mapped_column(TEXT, default=None, nullable=True)
    staking_period: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    network_fee_token_uuid: Mapped[Optional[str]] = mapped_column(
        'network_fee_token',
        TEXT,
        ForeignKey(f'{CRYPTO_TOKEN_TABLE}.uuid'),
        nullable=True,
    )
    memo: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    crypto_token_uuid: Mapped[Optional[str]] = mapped_column(
        'crypto_token_uuid',
        TEXT,
        ForeignKey(f'{CRYPTO_TOKEN_TABLE}.uuid'),
        nullable=True,
    )
    subject: Mapped[Optional[str]] = mapped_column(TEXT, default=None, nullable=True)
    fiat_prices_retry_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default='0'
    )
