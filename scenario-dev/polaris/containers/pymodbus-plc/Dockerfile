FROM python:3.11-slim

RUN pip install --no-cache-dir pymodbus==3.6.6

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 502

ENTRYPOINT ["/entrypoint.sh"]
