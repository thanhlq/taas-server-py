#!/bin/bash

# whenever you add deps to a workspace member, or add the members to
# the root project's deps so plain uv sync works.
uv sync --all-packages
