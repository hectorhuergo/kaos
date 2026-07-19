# Imagen oficial ligera de Python 3.13
FROM python:3.13-slim

# Instalar Git (requerido por la inicialización de KAOS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Configurar variables de entorno para optimizar Python y uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Instalar 'uv' de forma nativa descargando el binario oficial
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copiar todo el proyecto primero
COPY . .

# Sincronizar e instalar todas las dependencias del proyecto de forma congelada
RUN uv sync --frozen --no-dev

# Render asigna dinámicamente un puerto mediante la variable de entorno $PORT
EXPOSE 10000

# Comando de inicio: Forzamos a uv a incluir uvicorn bajo demanda al ejecutar el servidor
CMD ["sh", "-c", "uv run --with uvicorn kaos serve --port ${PORT:-10000} --host 0.0.0.0"]
