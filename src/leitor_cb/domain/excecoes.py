"""Exceções do domínio.

Substituem o retorno de strings de erro do script antigo, que podiam ser
confundidas com um resultado válido e acabar impressas na planilha.
"""


class LeitorCbError(Exception):
    """Erro base — permite capturar tudo do projeto num único except."""


class CodigoInvalidoError(LeitorCbError):
    """O código lido não obedece ao padrão FEBRABAN (tamanho ou conteúdo)."""


class DocumentoIlegivelError(LeitorCbError):
    """O arquivo não pôde ser aberto ou renderizado."""
