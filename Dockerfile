FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -e .

CMD ["uvicorn", "agentmesh.main:app", "--host", "0.0.0.0", "--port", "8000"]
