# Imagem do servidor local (`leitor-cb-web`).
#
# Duas etapas: a primeira monta o ambiente virtual com o uv, a segunda leva só
# o resultado. O uv e o cache de build ficam para trás — a imagem final não
# precisa saber compilar nada.

FROM python:3.14-slim AS construcao

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependências antes do código: enquanto o uv.lock não mudar, o Docker reaproveita
# esta camada e o rebuild depois de editar um .py leva segundos em vez de minutos.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
# --no-editable copia o pacote para dentro do .venv; editável deixaria um link
# apontando para /app/src, que a etapa final não recebe.
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.14-slim

# libgl1/libglib: o `import cv2` do opencv-python liga contra elas mesmo quando
# nenhuma janela é aberta, e a imagem slim não as traz.
# tzdata: sem ela o contêiner ignora o TZ e grava o histórico em UTC.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tzdata \
    && rm -rf /var/lib/apt/lists/*

# Usuário sem privilégios. UID 1000 é o do primeiro usuário na maioria dos Linux,
# o que faz o bind mount de ./data funcionar sem chown no servidor.
RUN useradd --uid 1000 --create-home leitor

WORKDIR /app

COPY --from=construcao --chown=leitor:leitor /app/.venv /app/.venv

# Criadas aqui, com dono certo, porque a aplicação as escreve na primeira
# execução e um volume vazio herda o dono do diretório que a imagem já tem.
RUN install -d -o leitor -g leitor \
    /app/data /app/data/input /app/data/uploads /app/data/output

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo \
    LEITOR_CB_DADOS=/app/data \
    LEITOR_CB_SAIDA=/app/data/output \
    LEITOR_CB_PORTA=8000
# 0.0.0.0 dentro do contêiner é o único jeito de a porta publicada responder;
# quem controla a exposição é o mapeamento de portas do compose, não isto.
ENV LEITOR_CB_HOST=0.0.0.0

# Falha no build em vez de crash loop no servidor: o cv2 liga contra as libs
# instaladas lá em cima, e uma que faltasse só apareceria como contêiner
# reiniciando sem parar, longe daqui. Depende do PATH acima para achar o venv.
RUN python -c "import cv2, fitz, zxingcpp"

USER leitor

EXPOSE 8000

# Sem curl na imagem slim; o próprio Python da aplicação faz a checagem.
# /api/saude não toca no banco e a porta vem do ambiente: apontar para /api/lotes
# abria duas conexões SQLite a cada 30s e marcava o contêiner como doente numa
# disputa de trava passageira, e a porta fixa mentia se LEITOR_CB_PORTA mudasse.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('LEITOR_CB_PORTA', '8000') + '/api/saude', timeout=4)"

CMD ["leitor-cb-web"]
