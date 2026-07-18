from __future__ import annotations

from typing import List, Optional

from advanced_alchemy.base import UUIDv7AuditBase
from sqlalchemy import (
    ARRAY,
    TEXT,
    Boolean,
    Integer,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.models.types import JSONText

from .contants import CRYPTO_TOKEN_TABLE


class CryptoToken(UUIDv7AuditBase):
    __tablename__ = CRYPTO_TOKEN_TABLE

    name: Mapped[str] = mapped_column(TEXT, nullable=False)
    symbol: Mapped[str] = mapped_column(TEXT, nullable=False)
    contract_address: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    blockchain: Mapped[str] = mapped_column(TEXT, nullable=False)
    network: Mapped[str] = mapped_column(TEXT, nullable=False)
    type: Mapped[str] = mapped_column(TEXT, nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    treasury_account: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    token_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    internal_token: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    char_symbol: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    priority: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    erc20_permit_supported: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
    erc20_permit_eip712_domain: Mapped[Optional[List[dict]]] = mapped_column(
        JSONB, nullable=True
    )
    erc20_permit_contract_domain: Mapped[Optional[dict]] = mapped_column(
        JSONText, server_default=text("'{}'::jsonb"), nullable=True
    )
    enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    token_icon_url: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    blockchain_icon_url: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    show_blockchain_icon: Mapped[Optional[bool]] = mapped_column(
        Boolean, server_default=text('false'), nullable=True
    )
    restrict_to_whitelist: Mapped[Optional[bool]] = mapped_column(
        Boolean, server_default=text('false'), nullable=True
    )
    compliance_enabled: Mapped[Optional[bool]] = mapped_column(
        Boolean, server_default=text('false'), nullable=True
    )
    delisted: Mapped[Optional[bool]] = mapped_column(
        Boolean, server_default=text('false'), nullable=True
    )
    is_stable_coin: Mapped[bool] = mapped_column(
        Boolean, server_default=text('false'), nullable=False
    )
    chain_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    categories: Mapped[List[str]] = mapped_column(
        ARRAY(TEXT),
        default=['CRYPTO'],
        server_default=text("'{CRYPTO}'::text[]"),
        nullable=False,
    )
    token_sale_term_required: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
    short_name: Mapped[str] = mapped_column(TEXT, nullable=False)
