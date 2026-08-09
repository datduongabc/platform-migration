FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl gosu && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user — defense in depth if the app is ever compromised via
# a dependency or upload-handling bug. /app is chowned at build time, but the
# /app/uploads bind mount is fixed up at container start instead (see
# entrypoint.sh) since a runtime volume mount overrides whatever ownership the
# image had at that path.
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --shell /bin/bash --create-home app && \
    chown -R app:app /app && \
    chmod +x entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Stays root here — entrypoint.sh chowns the uploads mount, then drops to the
# non-root `app` user via gosu before exec'ing uvicorn.
ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
