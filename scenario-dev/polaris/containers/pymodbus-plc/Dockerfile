# base image: python:3.11-slim
FROM python@sha256:311ea5bb79f1a238ee9e38f8d5f09cb3b4b244575cf49e27cf365ea7e60f11d4

RUN pip install --no-cache-dir pymodbus==3.6.6

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 502

ENTRYPOINT ["/entrypoint.sh"]
