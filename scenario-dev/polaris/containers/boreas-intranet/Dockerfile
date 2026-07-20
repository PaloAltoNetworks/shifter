# base image: python:3.11-slim
FROM python@sha256:e031123e3d85762b141ad1cbc56452ba69c6e722ebf2f042cc0dc86c47c0d8b3

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
