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

# Copiar archivos de empaquetado e instalar dependencias con el extra del dashboard
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra dashboard

# Copiar el resto del código del proyecto
COPY . .

# Render asigna dinámicamente un puerto mediante la variable de entorno $PORT
# Exponemos el puerto estándar por si acaso, pero el comando usará la variable de Render
EXPOSE 10000

# Comando de inicio leyendo la variable PORT asignada por Render
CMD ["sh", "-c", "uv run kaos serve --port ${PORT:-10000} --host 0.0.0.0"]
