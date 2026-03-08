FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    paho-mqtt==2.1.0 \
    numpy==1.26.4

# Copy the simulator source (nea_v2 files)
COPY . .

CMD ["python", "mqtt_simulator.py"]
