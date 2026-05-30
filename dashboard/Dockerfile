FROM python:3.11-slim
WORKDIR /dashboard
RUN pip install --no-cache-dir rich httpx
COPY . .
CMD ["python", "live.py", "--api_url", "http://api:8000", "--store_id", "STORE_BLR_002"]
