# Integration point for TASK-005 and TASK-007.
FROM python:3.12-slim-bookworm AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM dependencies AS runtime
RUN useradd --system --create-home enot
COPY --chown=enot:enot backend/ ./
COPY --chown=enot:enot analysis/TASK-003/calculator/ /app/analysis/TASK-003/calculator/
USER enot
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir -r requirements-test.txt
USER enot
CMD ["python", "-m", "pytest", "-q"]

FROM runtime AS app
