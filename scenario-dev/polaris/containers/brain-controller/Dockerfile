# base image: python:3.11-slim
FROM python@sha256:311ea5bb79f1a238ee9e38f8d5f09cb3b4b244575cf49e27cf365ea7e60f11d4

WORKDIR /srv/brain
COPY server.py /srv/brain/server.py

EXPOSE 9100

CMD ["python", "/srv/brain/server.py"]
