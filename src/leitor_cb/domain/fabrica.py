"""Roteamento entre as famílias de documento."""

from .conversores import ConversorArrecadacao, ConversorCobranca, ConversorLinhaDigitavel
from .models import CodigoBarras, LinhaDigitavel, TipoDocumento


class FabricaConversor:
    """Escolhe o conversor certo a partir do tipo do código.

    Ponto único de extensão: um novo padrão de documento entra registrando mais
    um conversor aqui, sem tocar no restante do pipeline.
    """

    def __init__(
        self,
        cobranca: ConversorLinhaDigitavel | None = None,
        arrecadacao: ConversorLinhaDigitavel | None = None,
    ) -> None:
        self._conversores: dict[TipoDocumento, ConversorLinhaDigitavel] = {
            TipoDocumento.COBRANCA: cobranca or ConversorCobranca(),
            TipoDocumento.ARRECADACAO: arrecadacao or ConversorArrecadacao(),
        }

    def para(self, codigo: CodigoBarras) -> ConversorLinhaDigitavel:
        return self._conversores[codigo.tipo]

    def converter(self, codigo: CodigoBarras) -> LinhaDigitavel:
        """Atalho para o caminho mais comum."""
        return self.para(codigo).converter(codigo)
