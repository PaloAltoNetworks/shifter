FROM python:3.12-alpine
RUN pip install --no-cache-dir pymodbus==3.12.1
COPY server.py /app/server.py
WORKDIR /app
# Production port 502
CMD ["python3", "server.py"]
