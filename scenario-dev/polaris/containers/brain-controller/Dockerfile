# base image: python:3.11-slim
FROM python@sha256:5f1cdbcab9a50594a79502dd73e885456d2a2fc31f1a1fa18484815b37ee9152

WORKDIR /srv/brain
COPY server.py /srv/brain/server.py

EXPOSE 9100

CMD ["python", "/srv/brain/server.py"]
