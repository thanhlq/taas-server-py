#  ULlib

The iam implementation using keycloak

## Overview

This lib provides the iam implementation using keycloak.

## Installation

This module is part of the monorepo workspace. Install dependencies using:

```bash
# From monorepo root
uv sync
```

## Usage

### Library Usage

```python
from iam_keycloak.domain.models import 
from iam_keycloak.services.iam_keycloak_service import Service

# Create a new iam_keycloak
iam_keycloak_entity = (
    name="Example ",
    description="Example description"
)

# Use service layer
service = Service(repository)
iam_keycloak_entity = service.create_iam_keycloak("Example", "Description")
```

### Domain Models

- ``: Main aggregate root
- `Id`: Value object for iam_keycloak identification

### Services

- `Service`: Business logic for iam_keycloak operations

### Repositories

- `Repository`: Abstract repository interface

## Development

### Running Tests

```bash
# Run tests for this module
uv run pytest libs/iam_keycloak/tests/

# Run with coverage
uv run pytest --cov=iam_keycloak libs/iam_keycloak/tests/
```

### Code Quality

```bash
# Format code
uv run ruff format libs/iam_keycloak/

# Lint code
uv run ruff check libs/iam_keycloak/

# Type checking
uv run pyright libs/iam_keycloak/
```

## Architecture

This lib follows the monorepo's architecture patterns:

- **Domain-Driven Design**: Clear separation of domain logic
- **Clean Architecture**: Dependencies point inward
- **Type Safety**: Comprehensive type annotations
- **Testing**: Unit and integration tests

## Dependencies

- `core`: Foundation types and interfaces
- `pydantic`: Data validation and serialization
