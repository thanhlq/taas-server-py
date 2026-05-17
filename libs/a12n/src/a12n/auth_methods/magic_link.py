"""Email + Magic Link authentication.

The link contains a short-lived, signed token. On click we look up the
opaque id in storage, mark it consumed, and resume the OAuth ``/authorize``
flow at ``next_url``.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from itsdangerous import BadSignature, URLSafeTimedSerializer

from iam_oauth.config import OAuthServerConfig
from iam_oauth.models.entities import MagicLinkToken
from iam_oauth.repositories import MagicLinkRepository, UserRepository


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class MagicLinkAuthenticator:
    def __init__(
        self,
        *,
        config: OAuthServerConfig,
        repo: MagicLinkRepository,
        user_repo: UserRepository,
        email_sender: EmailSender,
        signing_secret: str,
    ):
        self._cfg = config
        self._repo = repo
        self._user_repo = user_repo
        self._email = email_sender
        self._serializer = URLSafeTimedSerializer(signing_secret, salt='a12n-magic-link')

    async def request(self, *, email: str, next_url: Optional[str], base_url: str) -> None:
        token_id = uuid.uuid4().hex
        signed = self._serializer.dumps(token_id)
        await self._repo.save(MagicLinkToken(
            id=token_id,
            email=email,
            expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=self._cfg.magic_link_ttl),
            next_url=next_url,
        ))
        url = f'{base_url.rstrip("/")}/login/magic/callback?t={signed}'
        await self._email.send(
            to=email,
            subject=self._cfg.magic_link_subject,
            body=f'Click here to sign in (valid for 10 minutes):\n\n{url}\n',
        )

    async def consume(self, *, signed_token: str) -> MagicLinkToken:
        try:
            token_id = self._serializer.loads(signed_token, max_age=self._cfg.magic_link_ttl)
        except BadSignature as exc:
            raise PermissionError('Invalid or expired magic link') from exc

        record = await self._repo.pop(token_id)
        if record is None or record.consumed:
            raise PermissionError('Magic link already used or expired')
        if record.expires_at < datetime.now(tz=timezone.utc):
            raise PermissionError('Magic link expired')
        return record
