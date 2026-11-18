# syntax=docker/dockerfile:1
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --no-create-home --shell /usr/sbin/nologin agent
WORKDIR /app
# The pinned lockfile installs first so source edits reuse the dependency layer; it is mounted, not
# copied, so it never lands in the image.
RUN --mount=type=bind,source=requirements.txt,target=/tmp/requirements.txt \
    --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt
COPY pyproject.toml /build/
COPY src /build/src
RUN pip install --no-cache-dir --no-deps /build && rm -rf /build
COPY static ./static
ENV STATIC_DIR=/app/static
# A named volume mounted here starts as a copy of this folder, so on the EC2 instance the
# statements volume belongs to the agent user, who writes the uploads into it.
RUN install -d -o agent -g agent /statements
USER agent
EXPOSE 8030
CMD ["uvicorn", "calagent.platform.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8030"]
