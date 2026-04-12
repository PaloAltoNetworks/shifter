FROM python:3.12-slim
RUN pip install --no-cache-dir flask pymodbus==3.12.1
# server.py lives in A5-scada-generator/ per convention; build context is
# the parent mechag/ dir.
COPY A5-scada-generator/server.py /app/server.py
WORKDIR /app
ENV WEB_PORT=8080 MODBUS_PORT=502
EXPOSE 8080 502
CMD ["python3", "server.py"]
