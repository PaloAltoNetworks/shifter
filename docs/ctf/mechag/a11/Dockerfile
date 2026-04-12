FROM python:3.12-alpine
RUN pip install --no-cache-dir pymodbus==3.12.1
COPY A11-leg-controller/server.py /app/server.py
WORKDIR /app
CMD ["python3", "server.py"]
