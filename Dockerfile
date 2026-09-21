FROM python:3.12-slim-bookworm
WORKDIR /app
ENV APP_ENV=production PORT=3000 HOST=0.0.0.0 DATA_DIR=/app/data \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home app
COPY --chown=app:app dist ./dist
COPY --chown=app:app server ./server
COPY --chown=app:app gunicorn.conf.py ./
RUN mkdir -p /app/data && chown app:app /app/data
USER app
EXPOSE 3000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "server.wsgi:app"]
