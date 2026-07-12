"""Shared fixtures for the ``ews_worker`` tests.

Loads ``.env.test`` from the repository root before importing any app modules so
settings pick up the test configuration (local Kafka/Redis/Postgres).
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest
from dotenv import load_dotenv


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env.test").exists():
            return parent
    return Path(__file__).resolve().parents[3]


load_dotenv(_repo_root() / ".env.test", override=True)
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


def _kafka_reachable(bootstrap: str) -> bool:
    host, _, port = bootstrap.partition(":")
    try:
        with socket.create_connection((host, int(port or 9092)), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def kafka_bootstrap() -> str:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    if not _kafka_reachable(bootstrap):
        pytest.skip(f"Kafka not reachable at {bootstrap}")
    return bootstrap
