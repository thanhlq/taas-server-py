ARG REGISTRY="docker.io"
ARG PYTHON_BASE_IMAGE_VERSION=3.14.5-slim-bookworm

FROM ${REGISTRY}/python:${PYTHON_BASE_IMAGE_VERSION}
ENV DEBIAN_FRONTEND=noninteractive

RUN mkdir /app
WORKDIR /app

#############################
# Install other dependencies
#############################
# RUN --mount=type=cache,target=/var/cache/apt/ \
#     --mount=type=cache,target=/var/lib/apt/lists/ \
#     apt-get update && apt-get install -y --no-install-recommends nano curl g++ libpq-dev fontconfig libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 libpangocairo-1.0-0

#############################
# nvm environment variables
#############################
# RUN mkdir /nvm
# ENV NVM_DIR=/nvm
# ENV NODE_VERSION=24
# ENV NVM_SH_VERSION=0.40.5

#############################
# install nvm
# https://github.com/creationix/nvm#install-script
#############################
# RUN curl --silent -o- https://raw.githubusercontent.com/nvm-sh/nvm/v${NVM_SH_VERSION}/install.sh | bash

#############################
# install node and npm
#############################
# RUN rm /bin/sh && ln -s /bin/bash /bin/sh
# RUN source ${NVM_DIR}/nvm.sh \
#     && nvm install ${NODE_VERSION} \
#     && nvm alias default ${NODE_VERSION} \
#     && nvm use default \
#     && npm install --location=global yarn
# ENV NODE_PATH=${NVM_DIR}/v${NODE_VERSION}/lib/node_modules
# ENV PATH=${NVM_DIR}/versions/node/v${NODE_VERSION}/bin:$PATH


WORKDIR /app

# make sure we use system python and not .venv
ENV UV_PYTHON_DOWNLOADS=false
ENV UV_LINK_MODE=copy
ENV UV_SYSTEM_PYTHON=true
ENV UV_PROJECT_ENVIRONMENT="/usr/local/"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN pip install --no-cache-dir uv

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=libs/platform_core/pyproject.toml,target=libs/platform_core/pyproject.toml \
    --mount=type=bind,source=libs/http_fastapi/pyproject.toml,target=libs/http_fastapi/pyproject.toml \
    --mount=type=bind,source=libs/http_litestar/pyproject.toml,target=libs/http_litestar/pyproject.toml \
    --mount=type=bind,source=libs/db/pyproject.toml,target=libs/db/pyproject.toml \
    --mount=type=bind,source=libs/ews/pyproject.toml,target=libs/ews/pyproject.toml \
    --mount=type=bind,source=libs/iam/pyproject.toml,target=libs/iam/pyproject.toml \
    --mount=type=bind,source=libs/store_redis/pyproject.toml,target=libs/store_redis/pyproject.toml \
    --mount=type=bind,source=libs/store_memcached/pyproject.toml,target=libs/store_memcached/pyproject.toml \
    --mount=type=bind,source=libs/slowapi_advanced/pyproject.toml,target=libs/slowapi_advanced/pyproject.toml \
    --mount=type=bind,source=apps/ews_api/pyproject.toml,target=apps/ews_api/pyproject.toml \
    --mount=type=bind,source=apps/ews_api_litestar/pyproject.toml,target=apps/ews_api_litestar/pyproject.toml \
    --mount=type=bind,source=apps/ews_worker/pyproject.toml,target=apps/ews_worker/pyproject.toml \
    uv sync --frozen --no-install-workspace
############