FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 masar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER masar
EXPOSE 8000
# Hosts such as Render/Railway/Fly provide $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
