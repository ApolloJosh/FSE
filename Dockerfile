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
# Fly terminates TLS at its proxy and forwards plain HTTP to this port, so
# without these the app believes it is being browsed over http:// - it builds
# an http:// OAuth redirect_uri and GitHub refuses it. uvicorn reads
# X-Forwarded-Proto only from trusted addresses, and the default trusted list
# is loopback, which the proxy is not. The internal port is not publicly
# reachable, so trusting the proxy here is safe.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
