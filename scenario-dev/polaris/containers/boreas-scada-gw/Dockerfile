# base image: python:3.11-slim
FROM python@sha256:e06cc1111ed84189e91866447f562b89faadbfbbb9937cd67e6bf4172cdb45df

WORKDIR /srv/scada

RUN pip install --no-cache-dir flask==2.3.3 pymodbus==3.6.6

COPY hmi.py /srv/scada/hmi.py
COPY start.sh /srv/scada/start.sh
RUN chmod +x /srv/scada/start.sh

EXPOSE 8080 502

CMD ["/srv/scada/start.sh"]
