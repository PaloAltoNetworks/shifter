# base image: python:3.11-slim
FROM python@sha256:311ea5bb79f1a238ee9e38f8d5f09cb3b4b244575cf49e27cf365ea7e60f11d4

WORKDIR /srv/scada

RUN pip install --no-cache-dir flask==2.3.3 pymodbus==3.6.6

COPY hmi.py /srv/scada/hmi.py
COPY start.sh /srv/scada/start.sh
RUN chmod +x /srv/scada/start.sh

EXPOSE 8080 502

CMD ["/srv/scada/start.sh"]
