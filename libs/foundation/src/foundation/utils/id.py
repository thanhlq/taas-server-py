# from ..common.constants import TENANT_ID_LENGTH
import uuid

from fastnanoid import generate

# >= 3.14
v7_uuid = uuid.uuid7

alphabet_all: str = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-'
numbers_all: str = '0123456789'
MAX_ID_LENGTH = 36
TENANT_ID_LENGTH = 8


def generate_uuid() -> str:
    return str(v7_uuid())


def generate_tenant_id(size: int = TENANT_ID_LENGTH) -> str:
    return generate(size=size, alphabet=numbers_all)


def generate_id(
    size: int = 21,
    tenant_id: str | None = None,
    parent_id: str | None = None,
    alphabet: str = alphabet_all,
) -> str:

    if tenant_id and parent_id:
        return f'{tenant_id}-{parent_id}-{generate(size=MAX_ID_LENGTH - TENANT_ID_LENGTH - len(parent_id) - 2, alphabet=alphabet)}'
    elif tenant_id:
        return f'{tenant_id}-{generate_id(size=MAX_ID_LENGTH - TENANT_ID_LENGTH - 1)}'
    else:
        return generate(size=size, alphabet=alphabet)


def generate_otp(size: int = 6) -> str:
    return generate(size=size, alphabet=numbers_all)


# uv run python -m core.utils.id
# print(f'Generated Tenant ID: {generate_tenant_id()}')
# print(f'Generated ID: {generate_id(tenant_id="12345678")}')
# print(f'Generated UUID: {generate_uuid()}')
# print(f'Generated OTP: {generate_otp()}')
# print('---')
