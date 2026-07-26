# uv run python id.py
import random
import uuid

from fastnanoid import generate

# >= 3.14
v7_uuid = uuid.uuid7

alphabet_all: str = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-'
numbers_all: str = '0123456789'
MAX_ID_LENGTH = 36
TENANT_ID_LENGTH = 8


def generate_uuid() -> uuid.UUID:
    return v7_uuid()


def generate_db_id() -> uuid.UUID:
    """Generate a UUIDv7 primary key value.

    Matches the ``UUIDv7`` column type used by ``User.id`` (and other
    ``UUIDv7AuditBase`` models). Assign this to ``model.id`` before flush when
    the id is needed early (e.g. to set a foreign key such as
    ``Tenant.root_account_id``) instead of waiting for the DB-side default.
    """
    return v7_uuid()


def generate_tenant_id_str(size: int = TENANT_ID_LENGTH) -> str:
    return generate(size=size, alphabet=numbers_all)


def generate_tenant_id(from_size: int = 10000000, to_size: int = 99999999) -> int:
    return random.randint(from_size, to_size)


def random_int_by_size(size: int = 8) -> int:
    """Generate a random integer of a specific length."""
    if size < 1:
        raise ValueError("Size must be at least 1")
    lower_bound = 10 ** (size - 1)
    upper_bound = (10 ** size) - 1
    return random.randint(lower_bound, upper_bound)

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


# print(f'Generated Tenant ID: {random_int_by_size(6)}')
# print(f'Generated Tenant ID: {random_int_by_size(8)}')
