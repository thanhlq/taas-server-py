"""Test wiring for ``block-kaspa`` REST-client tests.

- Loads environment from ``taas-server-py/.env`` *before* any ``KaspaSettings``
  is instantiated (settings read ``os.environ`` at construction time).
- Picks the fixture directory from ``KASPA_NETWORK`` (``mainnet`` vs ``testnet``):
  ``tests/fixtures/<network>/{transactions,utxos}``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv


def _repo_root() -> Path:
    """Walk upwards to the workspace root (the dir holding ``.env``)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env").exists():
            return parent
    # Fallback: .../libs/block-kaspa/tests/unit_dev -> taas-server-py
    return Path(__file__).resolve().parents[4]


# Bootstrap env at import time — pytest imports conftest before collecting tests,
# so KASPA_* vars are in place before the test module and any settings read them.
load_dotenv(_repo_root() / ".env", override=False)


def resolve_network() -> str:
    """Normalize ``KASPA_NETWORK`` to the fixture folder name (mainnet/testnet)."""
    net = (os.environ.get("KASPA_NETWORK") or "testnet").lower()
    return "mainnet" if "main" in net else "testnet"


def tests_dir() -> Path:
    """.../tests (parent of this ``unit_dev`` package)."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def kaspa_network() -> str:
    return resolve_network()


@pytest.fixture(scope="session")
def fixtures_dir(kaspa_network: str) -> Path:
    d = tests_dir() / "fixtures" / kaspa_network
    if not d.exists():
        pytest.skip(f"fixtures dir not found: {d}")
    return d


@pytest.fixture
def rest_client():
    # Imported lazily so env is loaded first.
    from block_kaspa.client_rest.kaspa_rest_client import KaspaRestClient

    return KaspaRestClient(url=None)  # url=None -> uses settings.rest_url from env
