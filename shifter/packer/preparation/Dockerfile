# Build from repository root. Private adapters derive from this runtime and copy
# their contained contexts into /app/preparation/contexts before digest approval.
# base image: python3.12-trixie-slim
FROM ghcr.io/astral-sh/uv@sha256:3137a0b606f65a74ee0245f43dae219b09e8af98fc37fef20841cbceef35a646 AS builder
WORKDIR /build
COPY shifter/packer/pyproject.toml shifter/packer/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --output-file requirements.txt && \
    uv venv --python /usr/local/bin/python /opt/venv && \
    uv pip install --python /opt/venv/bin/python --no-config --require-hashes --only-binary :all: -r requirements.txt

# base image: python:3.12-slim-trixie
FROM python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf
LABEL maintainer="Shifter maintainers" \
      org.opencontainers.image.title="shifter-artifact-preparation" \
      org.opencontainers.image.description="Contained artifact preparation and independent verification" \
      org.opencontainers.image.source="https://github.com/Brad-Edwards/shifter" \
      org.opencontainers.image.licenses="MIT"
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY shifter/shifter_platform/shared/__init__.py shifter/shifter_platform/shared/enums.py \
     shifter/shifter_platform/shared/exceptions.py \
     shifter/shifter_platform/shared/operation_envelope.py shifter/shifter_platform/shared/artifact_preparation.py \
     shifter/shifter_platform/shared/preparation_grant.py ./shared/
COPY shifter/shifter_platform/shared/raes/__init__.py shifter/shifter_platform/shared/raes/preparation_contract.py \
     shifter/shifter_platform/shared/raes/preparation_inputs.py \
     shifter/shifter_platform/shared/raes/json_ingress.py ./shared/raes/
COPY shifter/packer/preparation ./preparation
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["/opt/venv/bin/python", "-m", "preparation.worker_client"]
