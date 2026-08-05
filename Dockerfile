FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-compile -r requirements.txt

# O backend não precisa carregar Angular, Java, testes ou arquivos de deploy.
# Copiar somente o runtime reduz a imagem e evita rebuilds quando o painel muda.
COPY app ./app
COPY config ./config

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
