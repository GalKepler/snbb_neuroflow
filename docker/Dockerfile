FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY neuroflow/ neuroflow/

RUN pip install --no-cache-dir .

ENTRYPOINT ["neuroflow"]
