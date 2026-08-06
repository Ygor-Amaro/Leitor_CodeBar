# Leitor_CB

Lê códigos de barras de boletos e guias (padrão FEBRABAN) e QR Codes PIX em PDFs
de pagamento, gera as linhas digitáveis e exporta um relatório CSV para o fluxo
de Contas a Pagar.

## Instalação

Requer [uv](https://docs.astral.sh/uv/) e Python 3.14.

```bash
uv sync
```

> Se o projeto estiver numa pasta sincronizada pelo OneDrive, o `uv` pode falhar
> com erro de hardlink. Nesse caso rode `UV_LINK_MODE=copy uv sync` (ou defina
> `UV_LINK_MODE=copy` no ambiente de uma vez).

## Uso

1. Coloque os PDFs em `data/input/`.
2. Rode:

```bash
uv run leitor-cb
```

3. O CSV sai em `data/output/leitura_<data>_<hora>.csv` e o resumo aparece no
   terminal.

O programa varre a página inteira automaticamente. Só quando não encontra nada
ele abre uma janela pedindo que você marque a área do código com o mouse —
arraste o retângulo e tecle ENTER, ou tecle ESC para pular a página.

### Opções

| Opção | Para quê |
| --- | --- |
| `--entrada CAMINHO` | Um PDF específico ou outra pasta (padrão: `data/input`) |
| `--saida PASTA` | Onde gravar o CSV (padrão: `data/output`) |
| `--sem-gui` | Nunca abre janela; o que não for lido vira pendência no relatório |
| `--sempre-manual` | Pede o recorte manual em toda página |
| `--zoom 2.0 3.0` | Resoluções tentadas em ordem; aumente para digitalizações ruins |
| `--sem-csv` | Só imprime no terminal |

Códigos de saída: `0` tudo lido, `1` há pendências para conferir, `2` erro de uso
(entrada inexistente ou sem PDFs).

### Relatório

Uma linha por código encontrado, com as colunas `arquivo`, `pagina`, `tipo`
(`cobranca`, `arrecadacao` ou `pix`), `codigo_barras`, `linha_digitavel`,
`dv_ok`, `status` e `observacao`.

O arquivo usa `;` e UTF-8 com BOM: abre no Excel em português com duplo clique.
As colunas de código vêm com um caractere de tabulação invisível na frente para
o Excel não converter o número em notação científica e perder dígitos — ao
copiar a célula, o valor colado é só os dígitos.

**`dv_ok = nao`** significa que o dígito verificador geral do código não bateu
com o resto dele. A linha continua no relatório, mas confira o documento antes
de pagar: quase sempre é leitura óptica errada.

## Configuração

Copie `.env.example` para `.env` para mudar os padrões (pastas, zoom, formatos
procurados). Os argumentos da linha de comando têm precedência sobre o `.env`.

## Desenvolvimento

```bash
uv run pytest                            # suíte completa
uv run pytest tests/test_conversores.py  # um arquivo
uv run pytest -k modulo_11               # um caso
uv run ruff check .                      # lint
uv run ruff check . --fix                # lint com correção automática
```

A arquitetura está descrita em [CLAUDE.md](CLAUDE.md).
