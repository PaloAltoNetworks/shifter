FROM python:3.12-slim
RUN pip install --no-cache-dir flask pymodbus==3.12.1
COPY server.py /app/server.py
WORKDIR /app
ENV WEB_PORT=8080 MODBUS_PORT=502
EXPOSE 8080 502
CMD ["python3", "server.py"]
