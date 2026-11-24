FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home researcher && mkdir -p /app/data && chown -R researcher:researcher /app
USER researcher
EXPOSE 8000
CMD ["python", "scripts/run.py", "--host", "0.0.0.0"]
