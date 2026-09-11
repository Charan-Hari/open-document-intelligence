# Single-container image for a free, no-card demo deployment (e.g. Hugging
# Face Spaces). Serves the FastAPI backend and the static web UI from one
# process on port 7860 (the port Hugging Face Spaces expects for Docker SDK).
FROM python:3.12-slim

WORKDIR /app

# Install the API package (core dependencies only; OCR/ML extras are optional
# and add significant image size, so they're left out of the default demo).
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/src apps/api/src
RUN pip install --no-cache-dir ./apps/api

# Bundle the static web UI so the API process can serve it directly.
COPY apps/web /app/web

ENV ODI_WEB_DIR=/app/web
ENV ODI_DATA_DIR=/app/.data
ENV ODI_ALLOWED_ORIGINS=""

EXPOSE 7860

CMD ["uvicorn", "open_document_intelligence.main:app", "--host", "0.0.0.0", "--port", "7860"]
