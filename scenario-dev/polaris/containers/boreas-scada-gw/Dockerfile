FROM python:3.11-slim

WORKDIR /srv/scada

RUN pip install --no-cache-dir flask==2.3.3 pymodbus==3.6.6

COPY hmi.py /srv/scada/hmi.py
COPY start.sh /srv/scada/start.sh
RUN chmod +x /srv/scada/start.sh

EXPOSE 8080 502

CMD ["/srv/scada/start.sh"]
