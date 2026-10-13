FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app.py config.py ./
COPY routes ./routes
COPY services ./services
COPY utils ./utils

# Sem privilégios de administrador dentro do contêiner.
RUN useradd --system --uid 10001 --no-create-home apura
USER apura

EXPOSE 5000

# Threads, não só processos: cada análise espera a API em uma thread (veja services/replies.py).
CMD ["sh", "-c", "exec gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT:-5000} --workers 2 --threads 8 --timeout 60 --no-control-socket"]
