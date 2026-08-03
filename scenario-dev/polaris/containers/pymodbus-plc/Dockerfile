# base image: python:3.11-slim
FROM python@sha256:5f1cdbcab9a50594a79502dd73e885456d2a2fc31f1a1fa18484815b37ee9152

RUN pip install --no-cache-dir pymodbus==3.6.6

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 502

ENTRYPOINT ["/entrypoint.sh"]
