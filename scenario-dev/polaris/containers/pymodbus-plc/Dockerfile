# base image: python:3.11-slim
FROM python@sha256:e06cc1111ed84189e91866447f562b89faadbfbbb9937cd67e6bf4172cdb45df

RUN pip install --no-cache-dir pymodbus==3.6.6

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 502

ENTRYPOINT ["/entrypoint.sh"]
