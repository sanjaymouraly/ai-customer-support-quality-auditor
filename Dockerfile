FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml requirements.txt README.md ./
COPY auditor ./auditor
COPY backend ./backend
COPY frontend ./frontend
RUN pip install --no-cache-dir -e .
COPY . .
RUN mkdir -p data/policies data/synthetic data/annotations
ENV PYTHONPATH=/app
EXPOSE 8000 8501
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
