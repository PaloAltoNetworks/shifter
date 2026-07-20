# base image: python:3.11-slim
FROM python@sha256:311ea5bb79f1a238ee9e38f8d5f09cb3b4b244575cf49e27cf365ea7e60f11d4

WORKDIR /srv/intranet

RUN apt-get update \
 && apt-get install -y --no-install-recommends sqlite3 \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask==2.3.3

# The generator places /.env, /srv/intranet/wiki.html etc. under /generated;
# the compose emitter maps those onto the correct paths at runtime. The
# baseline application (with intentional SQLi + LFI + exposed .env) is
# inlined here so the image is self-contained even if the scenario provides
# no content.
COPY app.py /srv/intranet/app.py

EXPOSE 80

CMD ["python", "/srv/intranet/app.py"]
