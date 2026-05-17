"""WebAuthn / Passkey authentication backed by ``py_webauthn``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticationCredential,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    RegistrationCredential,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from iam_oauth.config import OAuthServerConfig
from iam_oauth.models.entities import PasskeyCredential, User
from iam_oauth.repositories import PasskeyRepository


class PasskeyAuthenticator:
    def __init__(self, *, config: OAuthServerConfig, repo: PasskeyRepository):
        self._cfg = config
        self._repo = repo

    # ---------------- registration ------------------------------------------
    def begin_registration(self, *, user: User) -> dict[str, Any]:
        opts = generate_registration_options(
            rp_id=self._cfg.webauthn_rp_id,
            rp_name=self._cfg.webauthn_rp_name,
            user_id=user.id.encode(),
            user_name=user.email,
            user_display_name=user.email,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        return opts.model_dump(by_alias=True, exclude_none=True)

    async def finish_registration(
        self, *, user: User, expected_challenge: bytes, credential: dict[str, Any]
    ) -> PasskeyCredential:
        verification = verify_registration_response(
            credential=RegistrationCredential.parse_obj(credential),
            expected_challenge=expected_challenge,
            expected_rp_id=self._cfg.webauthn_rp_id,
            expected_origin=self._cfg.webauthn_origin,
        )
        cred = PasskeyCredential(
            credential_id=verification.credential_id,
            user_id=user.id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            aaguid=verification.aaguid,
            created_at=datetime.now(tz=timezone.utc),
        )
        await self._repo.save(cred)
        return cred

    # ---------------- authentication ----------------------------------------
    async def begin_authentication(self, *, user: User | None = None) -> dict[str, Any]:
        allow_credentials = []
        if user is not None:
            stored = await self._repo.list_for_user(user.id)
            allow_credentials = [
                PublicKeyCredentialDescriptor(id=c.credential_id) for c in stored
            ]
        opts = generate_authentication_options(
            rp_id=self._cfg.webauthn_rp_id,
            allow_credentials=allow_credentials,
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        return opts.model_dump(by_alias=True, exclude_none=True)

    async def finish_authentication(
        self, *, expected_challenge: bytes, credential: dict[str, Any]
    ) -> PasskeyCredential:
        parsed = AuthenticationCredential.parse_obj(credential)
        stored = await self._repo.get(parsed.raw_id)
        if stored is None:
            raise PermissionError('Unknown credential')

        verification = verify_authentication_response(
            credential=parsed,
            expected_challenge=expected_challenge,
            expected_rp_id=self._cfg.webauthn_rp_id,
            expected_origin=self._cfg.webauthn_origin,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
        )
        await self._repo.update_sign_count(
            stored.credential_id,
            verification.new_sign_count,
            datetime.now(tz=timezone.utc),
        )
        return stored
