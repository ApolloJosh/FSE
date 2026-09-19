FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 FSX_ENV=production

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fsx/ ./fsx/
COPY app/ ./app/
COPY data/ ./data/
COPY roster.txt ./

# SQLite lives on the mounted disk, not in the image, or every deploy wipes
# everyone's portfolio.
ENV FSX_DB=/data/market.db
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
