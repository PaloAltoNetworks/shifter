FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        openssh-client sshpass ca-certificates postgresql-client \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir flask pymodbus
# server.py lives in A3-web-app/ per convention; build context is the
# parent mechag/ dir.
COPY A3-web-app/server.py /app/server.py
RUN mkdir -p /var/www/docs && \
    printf 'Boreas Systems internal document archive.\nSee company wiki for document index.\n' > /var/www/docs/README.txt && \
    printf 'Q3 2025 expense summary placeholder - full file in Procurement share.\n' > /var/www/docs/q3-expense-summary.txt
WORKDIR /app
ENV A3_PORT=80
EXPOSE 80
CMD ["python3", "server.py"]
