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

## Uso pelo navegador

```bash
uv run leitor-cb-web
```

Abra <http://127.0.0.1:8000>, escolha os PDFs, acompanhe o progresso e baixe o
CSV. Os lotes anteriores ficam listados na mesma página, com link para reabrir o
relatório.

O servidor escuta só em `127.0.0.1`: nada é publicado na rede do escritório. O
histórico (situação dos lotes e as leituras) fica num SQLite em
`data/leitor_cb.sqlite3`.

### Copiando as linhas para o banco

Cada linha do relatório tem um botão **Copiar** que leva o código cru, do jeito
que se cola no internet banking. Ao copiar, a linha é marcada como feita e fica
esmaecida — é assim que se acha onde parou depois de uma interrupção. A marca
também pode ser ligada e desligada à mão na primeira coluna, e vale só para o
seu navegador: outra pessoa abrindo o mesmo relatório vê a lista limpa.

Acima da tabela dá para filtrar por **Para conferir** (as pendências e os DV que
não bateram), **Prontas**, ou buscar por nome de arquivo, código ou observação.
**Ocultar as já copiadas** encurta a lista conforme o trabalho anda.

### Recorte manual pelo navegador

Quando uma página sai como pendência, a coluna **recortar** abre a página
renderizada. Arraste o mouse sobre o código de barras ou o QR Code e clique em
**Ler seleção** — o servidor relê só aquele pedaço, substitui a linha do
relatório e regenera o CSV. `Esc` limpa a marcação. Também dá para aumentar o
zoom e mandar reler a página inteira, útil em digitalização ruim: a releitura
parte da ampliação escolhida na tela e, se não achar nada, tenta ampliações
maiores antes de desistir.

Releitura que não encontra nada **não apaga** o que já estava na página: o
relatório fica como estava e a tela avisa. Vale tentar de novo marcando uma área
um pouco maior, com as bordas claras do código dentro da seleção.

É o equivalente do recorte da CLI. A diferença é que o `cv2.selectROI` abriria a
janela na máquina que roda o servidor; aqui o recorte acontece no navegador de
quem está usando.

### Os PDFs enviados e o prazo de retenção

O recorte manual precisa do arquivo original, então os PDFs enviados ficam em
`data/uploads/` por **24 horas** (`LEITOR_CB_RETENCAO_HORAS`) e depois são
apagados sozinhos — a limpeza roda quando o servidor sobe e a cada novo envio.
Para apagar antes, use **Descartar arquivos agora** na tela do lote.

Descartar não afeta o relatório: o CSV continua disponível para download. O que
se perde é a possibilidade de recortar aquelas páginas à mão.

Existe também uma API REST, útil para automatizar o envio — documentação
navegável em <http://127.0.0.1:8000/docs>:

| Rota | Para quê |
| --- | --- |
| `POST /api/lotes` | Envia PDFs (multipart, campo `arquivos`) e abre um lote |
| `GET /api/lotes` | Lotes recentes com o resumo de cada um |
| `GET /api/lotes/{id}` | Situação do lote e as leituras extraídas |
| `GET /api/lotes/{id}/relatorio` | Baixa o CSV |
| `GET .../documentos/{n}/paginas/{p}/imagem?zoom=2` | Página rasterizada em PNG |
| `POST .../documentos/{n}/paginas/{p}/releitura?zoom=2` | Relê a página inteira; com corpo `{x, y, largura, altura, zoom}`, só a área marcada |
| `DELETE /api/lotes/{id}/arquivos` | Descarta os PDFs antes do prazo |

Ajustes por variável de ambiente (ou `.env`): `LEITOR_CB_HOST`,
`LEITOR_CB_PORTA`, `LEITOR_CB_DADOS`, `LEITOR_CB_TAMANHO_MAXIMO_MB`,
`LEITOR_CB_MAXIMO_ARQUIVOS`, `LEITOR_CB_RETENCAO_HORAS`.

## Implantação com Docker

Para deixar o leitor no ar num servidor local, sem depender de alguém manter um
terminal aberto. Requer Docker com o plugin Compose.

```bash
docker compose up -d --build   # sobe (e reconstrói a imagem)
docker compose logs -f         # acompanha
docker compose down            # derruba
```

O serviço volta sozinho depois de reinício do servidor (`restart: unless-stopped`)
e responde em <http://127.0.0.1:8000> **na própria máquina**. Só a versão web
roda no contêiner: a CLI abre a janela do OpenCV, que não existe ali.

`./data` é montado para dentro do contêiner — é a única coisa que sobrevive a
`docker compose down`. Ficam nela o histórico (`leitor_cb.sqlite3`), os CSVs em
`output/` e os PDFs enviados em `uploads/`, estes últimos apagados pelo prazo de
retenção.

### Liberar para a rede do escritório

Por padrão a porta é publicada em `127.0.0.1:8000`, então nenhuma outra máquina
alcança o serviço. Para abrir, troque em `docker-compose.yml`:

```yaml
    ports:
      - "8000:8000"
```

Não há login: quem chega na porta lê todos os boletos enviados e baixa os
relatórios. Abra só numa rede em que isso seja aceitável.

O botão **Copiar** funciona pela rede em HTTP: o navegador reserva a API moderna
de área de transferência para endereços seguros, e fora deles o sistema cai no
caminho antigo, que copia o campo selecionado. Se algum navegador do escritório
recusar os dois, o botão avisa *tecle Ctrl+C* com o código já selecionado.

### Se der erro de permissão em `data/`

O contêiner roda como usuário comum (UID 1000). Quando o dono da pasta no
servidor for outro, ajuste uma vez:

```bash
sudo chown -R 1000:1000 data
```

## Uso pelo terminal

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

Os atalhos ficam no `pyproject.toml`; `uv run task --list` mostra todos.

```bash
uv run task web        # sobe o servidor
uv run task ler        # processa data/input
uv run task testes     # suíte completa
uv run task lint       # ruff
uv run task arrumar    # ruff --fix
uv run task conferir   # lint + testes, antes de commitar
```

Para rodar um pedaço da suíte, chame o pytest direto:

```bash
uv run pytest tests/test_conversores.py  # um arquivo
uv run pytest -k modulo_11               # um caso
```
