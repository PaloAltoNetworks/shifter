# base image: python:3.11-slim
FROM python@sha256:e06cc1111ed84189e91866447f562b89faadbfbbb9937cd67e6bf4172cdb45df

WORKDIR /srv/brain
COPY server.py /srv/brain/server.py

EXPOSE 9100

CMD ["python", "/srv/brain/server.py"]
