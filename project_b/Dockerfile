FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash gettext \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check

COPY . .

RUN bash -n /app/start-render.sh \
    && python -m django compilemessages -l uk --ignore=staticfiles

EXPOSE 8000

CMD ["gunicorn", "warehouse_project.wsgi:application", "--workers", "1", "--access-logfile", "-", "--error-logfile", "-"]