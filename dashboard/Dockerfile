FROM python:3.11-slim
WORKDIR /dashboard
RUN pip install --no-cache-dir streamlit pandas plotly httpx
COPY . .
EXPOSE 3000
CMD ["streamlit", "run", "app.py", "--server.port", "3000", "--server.address", "0.0.0.0"]
