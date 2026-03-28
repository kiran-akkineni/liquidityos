FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Runtime config
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Use shell form so $PORT is expanded at runtime
CMD sh -c "python scripts/prod_seed.py && gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120 app.main:app"
