# base image: python:3.11-slim
FROM python@sha256:e031123e3d85762b141ad1cbc56452ba69c6e722ebf2f042cc0dc86c47c0d8b3

WORKDIR /srv/scada

RUN pip install --no-cache-dir flask==2.3.3 pymodbus==3.6.6

COPY hmi.py /srv/scada/hmi.py
COPY start.sh /srv/scada/start.sh
RUN chmod +x /srv/scada/start.sh

EXPOSE 8080 502

CMD ["/srv/scada/start.sh"]
