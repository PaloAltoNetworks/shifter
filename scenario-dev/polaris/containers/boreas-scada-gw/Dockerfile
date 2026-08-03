# base image: python:3.11-slim
FROM python@sha256:5f1cdbcab9a50594a79502dd73e885456d2a2fc31f1a1fa18484815b37ee9152

WORKDIR /srv/scada

RUN pip install --no-cache-dir flask==2.3.3 pymodbus==3.6.6

COPY hmi.py /srv/scada/hmi.py
COPY start.sh /srv/scada/start.sh
RUN chmod +x /srv/scada/start.sh

EXPOSE 8080 502

CMD ["/srv/scada/start.sh"]
