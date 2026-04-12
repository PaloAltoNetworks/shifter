FROM python:3.12-slim
RUN pip install --no-cache-dir flask
COPY server.py /app/server.py
WORKDIR /app
ENV A0_PORT=80
EXPOSE 80
CMD ["python3", "server.py"]
