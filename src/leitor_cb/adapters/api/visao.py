"""Motor de templates e os filtros que as telas usam.

O autoescape do Jinja fica ligado (padrão do Starlette) e segura o outro lado do
problema que o CSV tem: nome de arquivo e payload de PIX vêm de PDFs de
terceiros. Nenhum template pode marcar esses valores com `|safe`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

DIRETORIO_WEB = Path(__file__).resolve().parent.parent / "web"
DIRETORIO_TEMPLATES = DIRETORIO_WEB / "templates"
DIRETORIO_ESTATICOS = DIRETORIO_WEB / "static"

# A máscara da linha digitável não está aqui: é `ResultadoLeitura.linha_formatada`,
# no domínio, para que a tela e a API não formatem o mesmo número de dois jeitos.


def momento(valor: datetime) -> str:
    return valor.strftime("%d/%m/%Y %H:%M")


templates = Jinja2Templates(directory=DIRETORIO_TEMPLATES)
templates.env.filters["momento"] = momento
