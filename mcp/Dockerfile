# syntax=docker/dockerfile:1
#
# The optional MCP service (#164, R-73, D-91). Built exactly like the API image
# (server/Dockerfile): two stages, a lock verified by hash, base images pinned by
# digest, a non-root user, and no pip, shell or package manager in the runtime image.
#
# It holds NO credential and writes nothing: compose runs it read-only with every
# capability dropped, and it is in a profile, so it does not start unless asked.

FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src

# --require-hashes refuses anything not in the lock; the project itself is not
# installed (the runtime stage copies the source in and sets PYTHONPATH).
COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --require-hashes --no-deps -r requirements.txt \
 && /opt/venv/bin/pip uninstall --yes pip setuptools


FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

# Non-root, no login shell, no home directory.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 10002 chaimcp

# The base image ships pip, setuptools and ensurepip for its own interpreter; nothing
# here installs anything at runtime, so they go (and with them the vendored copies of
# libraries that vulnerability scanners flag in a place this service can never use).
# The paths name no Python version (python3.*), so a new base image cannot keep its
# pip by moving it to a directory this line does not name (D-93).
RUN rm -rf /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* \
           /usr/local/bin/wheel /usr/local/bin/easy_install* \
           /usr/local/lib/python3.*/site-packages/pip \
           /usr/local/lib/python3.*/site-packages/pip-* \
           /usr/local/lib/python3.*/site-packages/setuptools* \
           /usr/local/lib/python3.*/site-packages/pkg_resources \
           /usr/local/lib/python3.*/site-packages/wheel* \
           /usr/local/lib/python3.*/site-packages/_distutils_hack \
           /usr/local/lib/python3.*/site-packages/distutils-precedence.pth \
           /usr/local/lib/python3.*/ensurepip

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=root:root chai_mcp ./chai_mcp

# Last, because RUN needs a shell: take the shells and the package manager out of the
# runtime image. Nothing here starts a shell (CMD and HEALTHCHECK are exec form), and
# nothing installs anything at runtime. After this line no RUN can follow.
RUN rm -f /usr/bin/dash /usr/bin/bash /usr/bin/sh /bin/sh /bin/bash /bin/dash \
          /usr/bin/rbash /usr/bin/apt /usr/bin/apt-get /usr/bin/apt-cache \
          /usr/bin/apt-config /usr/bin/apt-mark /usr/bin/apt-key /usr/bin/apt-cdrom \
          /usr/bin/dpkg /usr/bin/dpkg-* /usr/sbin/dpkg-*

USER 10002:10002

EXPOSE 8000

# Python, not curl: the slim image has no curl. /healthz is served to any Host and
# says nothing about the data.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request; p=os.environ.get('MCP_PORT') or '8000'; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=3).status==200 else 1)"]

# exec form, no shell: python is PID 1 and receives SIGTERM directly.
CMD ["python", "-m", "chai_mcp"]
