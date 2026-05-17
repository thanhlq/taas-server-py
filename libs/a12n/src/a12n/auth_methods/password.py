"""Password authentication using Argon2id."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from zxcvbn import zxcvbn  # type: ignore[import-untyped]

from iam_oauth.config import OAuthServerConfig


class PasswordPolicyError(ValueError):
    pass


class PasswordAuthenticator:
    def __init__(self, *, config: OAuthServerConfig):
        self._cfg = config
        self._hasher = PasswordHasher()

    # ------------------------------------------------------------------ hash
    def hash(self, password: str) -> str:
        self.assert_policy(password)
        return self._hasher.hash(password)

    def verify(self, *, password_hash: str | None, password: str) -> bool:
        if not password_hash:
            return False
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHash):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)

    # ---------------------------------------------------------------- policy
    def assert_policy(self, password: str) -> None:
        if len(password) < self._cfg.password_min_length:
            raise PasswordPolicyError(
                f'Password must be at least {self._cfg.password_min_length} characters.'
            )
        result = zxcvbn(password)
        if result['score'] < self._cfg.password_min_zxcvbn_score:
            feedback = result.get('feedback', {}).get('warning') or 'too weak'
            raise PasswordPolicyError(f'Password too weak: {feedback}')
