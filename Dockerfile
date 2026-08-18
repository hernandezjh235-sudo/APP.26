FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Apply the tested Undefeated V1.10.2 Savant adapter to app.py on every start.
# The bootstrap is idempotent and also restores the Savant profile into a mounted
# learning_data volume before Streamlit starts.
CMD ["sh", "-c", "python bootstrap_v1102.py && python -m py_compile app.py && streamlit run app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true"]
