FROM python:3.13-slim

WORKDIR /app

COPY lambda/organization_integration/requirements.txt .
RUN apt-get update && apt-get install -y libfreetype6-dev \
    && pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

COPY src .
COPY lambda/organization_integration/app.py .

CMD ["python", "app.py"]