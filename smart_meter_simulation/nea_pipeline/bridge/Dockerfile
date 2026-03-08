FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    paho-mqtt==2.1.0 \
    kafka-python-ng==2.2.3 \
    psycopg2-binary==2.9.9 \
    python-dotenv==1.0.1

COPY . .

CMD ["python", "bridge.py"]
