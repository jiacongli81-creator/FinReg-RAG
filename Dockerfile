FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY vendor/MinerU /tmp/MinerU
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt /tmp/MinerU \
    && rm -rf /tmp/MinerU

COPY app /app/app
COPY scripts /app/scripts

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
