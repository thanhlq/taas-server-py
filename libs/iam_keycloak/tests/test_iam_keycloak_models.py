"""Tests for iam_keycloak domain models."""

from datetime import datetime
from uuid import uuid4

import pytest
from iam_keycloak.domain.models import IamKeycloak, IamKeycloakId


class TestIamKeycloak:
    """Tests for IamKeycloak entity."""

    def test_create_iam_keycloak(self):
        """Test creating a iam_keycloak."""
        iam_keycloak_entity = IamKeycloak(
            name='Test IamKeycloak', description='Test description'
        )

        assert iam_keycloak_entity.name == 'Test IamKeycloak'
        assert iam_keycloak_entity.description == 'Test description'
        assert iam_keycloak_entity.is_active is True
        assert iam_keycloak_entity.id is not None
        assert iam_keycloak_entity.created_at is not None
        assert iam_keycloak_entity.updated_at is not None

    def test_activate_iam_keycloak(self):
        """Test activating a iam_keycloak."""
        iam_keycloak_entity = IamKeycloak(name='Test IamKeycloak', is_active=False)

        original_updated_at = iam_keycloak_entity.updated_at
        iam_keycloak_entity.activate()

        assert iam_keycloak_entity.is_active is True
        assert iam_keycloak_entity.updated_at > original_updated_at

    def test_deactivate_iam_keycloak(self):
        """Test deactivating a iam_keycloak."""
        iam_keycloak_entity = IamKeycloak(name='Test IamKeycloak', is_active=True)

        original_updated_at = iam_keycloak_entity.updated_at
        iam_keycloak_entity.deactivate()

        assert iam_keycloak_entity.is_active is False
        assert iam_keycloak_entity.updated_at > original_updated_at


class TestIamKeycloakId:
    """Tests for IamKeycloakId value object."""

    def test_create_iam_keycloak_id(self):
        """Test creating a iam_keycloak ID."""
        test_uuid = uuid4()
        iam_keycloak_id = IamKeycloakId(value=test_uuid)

        assert iam_keycloak_id.value == test_uuid
