FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Railway/Docker production startup. The launcher keeps pushed app.py untouched,
# applies proven runtime guards to runtime_app.py, uses Railway's PORT, and
# disables source-file watching/reload loops.
CMD ["python", "tools/launch_stable.py"]
