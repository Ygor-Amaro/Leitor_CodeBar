/* Copiar a linha digitável e filtrar a tabela — as duas coisas que só fazem
 * sentido no navegador.
 *
 * Copiar é o gesto mais repetido do sistema: uma linha por boleto, dezenas por
 * lote. Daí o botão, a confirmação visível e a marca de "já copiei esta", que é
 * como quem foi interrompido acha onde parou. Filtrar não vai ao servidor —
 * são dezenas de linhas já desenhadas.
 *
 * Tudo por delegação no documento e reaplicado a cada troca do HTMX, que
 * substitui a tabela inteira ao fim do lote e a cada releitura.
 */
(function () {
  'use strict';

  var CHAVE = 'leitor-cb:copiadas';
  var LOTES_LEMBRADOS = 20;
  var AVISO_MS = 1600;

  // ------------------------------------------------------------------ memória

  /* Guarda o endereço da linha (documento-página-ordem), nunca o código: é
   * marcador de leitura, não uma segunda cópia de dado financeiro. */
  function lido() {
    try {
      return JSON.parse(window.localStorage.getItem(CHAVE)) || {};
    } catch (erro) {
      return {};
    }
  }

  function gravar(mapa) {
    try {
      var lotes = Object.keys(mapa);
      // A tela mostra vinte lotes; lembrar mais só faria crescer para sempre.
      while (lotes.length > LOTES_LEMBRADOS) {
        delete mapa[lotes.shift()];
      }
      window.localStorage.setItem(CHAVE, JSON.stringify(mapa));
    } catch (erro) {
      // Armazenamento bloqueado: a marcação vale só nesta visita, o que é
      // melhor que quebrar a tela.
    }
  }

  function marcadas(lote) {
    return lido()[lote] || [];
  }

  function registrar(lote, chave, ligada) {
    var mapa = lido();
    var atuais = mapa[lote] || [];
    var posicao = atuais.indexOf(chave);

    if (ligada && posicao === -1) {
      atuais.push(chave);
    } else if (!ligada && posicao !== -1) {
      atuais.splice(posicao, 1);
    }

    mapa[lote] = atuais;
    gravar(mapa);
  }

  // -------------------------------------------------------------------- copiar

  function copiarTexto(campo) {
    campo.focus();
    campo.select();
    campo.setSelectionRange(0, campo.value.length);

    // `navigator.clipboard` só existe em contexto seguro, e pela rede em
    // http://ip-do-servidor não está lá. O campo já está selecionado, então o
    // caminho antigo copia a seleção.
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(campo.value).then(function () {
        return true;
      }, comSelecao);
    }
    return Promise.resolve(comSelecao());

    function comSelecao() {
      try {
        return document.execCommand('copy');
      } catch (erro) {
        return false;
      }
    }
  }

  function avisar(botao, texto, classe) {
    if (botao.dataset.rotulo === undefined) {
      botao.dataset.rotulo = botao.textContent.trim();
    }
    window.clearTimeout(Number(botao.dataset.relogio));

    botao.textContent = texto;
    botao.classList.add(classe);
    botao.dataset.relogio = String(
      window.setTimeout(function () {
        botao.textContent = botao.dataset.rotulo;
        botao.classList.remove(classe);
      }, AVISO_MS)
    );
  }

  function aoCopiar(botao) {
    var caixa = botao.closest('.copia');
    var campo = caixa && caixa.querySelector('input');
    if (!campo) {
      return;
    }

    copiarTexto(campo).then(function (deuCerto) {
      if (!deuCerto) {
        // O campo segue selecionado: a instrução é executável na hora.
        avisar(botao, 'tecle Ctrl+C', 'falhou');
        return;
      }

      avisar(botao, 'copiado ✓', 'copiado');

      var linha = botao.closest('tr');
      var caixinha = linha && linha.querySelector('[data-copiada]');
      if (caixinha && !caixinha.checked) {
        caixinha.checked = true;
        aoMarcar(caixinha);
      }
    });
  }

  // ------------------------------------------------------------------ marcação

  function aoMarcar(caixinha) {
    var linha = caixinha.closest('tr');
    var tabela = caixinha.closest('[data-tabela]');
    if (!linha || !tabela) {
      return;
    }

    linha.classList.toggle('copiada', caixinha.checked);
    registrar(tabela.dataset.lote, linha.dataset.linha, caixinha.checked);
    filtrar(tabela);
  }

  function restaurar(tabela) {
    var lembradas = marcadas(tabela.dataset.lote);

    Array.prototype.forEach.call(tabela.querySelectorAll('tbody tr'), function (linha) {
      var caixinha = linha.querySelector('[data-copiada]');
      if (!caixinha) {
        return;
      }
      caixinha.checked = lembradas.indexOf(linha.dataset.linha) !== -1;
      linha.classList.toggle('copiada', caixinha.checked);
    });
  }

  // ------------------------------------------------------------------- filtrar

  function barraDe(tabela) {
    var cartao = tabela.closest('.cartao') || document;
    return cartao.querySelector('[data-filtros]');
  }

  function filtrar(tabela) {
    var barra = barraDe(tabela);
    if (!barra) {
      return;
    }

    var busca = barra.querySelector('[data-busca]');
    var procurado = busca ? busca.value.trim().toLowerCase() : '';
    var ativo = barra.querySelector('.chip.ativo');
    var modo = ativo ? ativo.dataset.filtro : 'todas';
    var ocultarCopiadas = barra.querySelector('[data-ocultar-copiadas]');
    var esconder = ocultarCopiadas ? ocultarCopiadas.checked : false;

    var linhas = tabela.querySelectorAll('tbody tr');
    var contas = { todas: linhas.length, atencao: 0, prontas: 0 };
    var visiveis = 0;

    Array.prototype.forEach.call(linhas, function (linha) {
      var atencao = linha.dataset.atencao === '1';
      var copiada = linha.classList.contains('copiada');

      if (atencao) {
        contas.atencao += 1;
      } else {
        contas.prontas += 1;
      }

      var cabe =
        (modo === 'todas' || (modo === 'atencao' && atencao) || (modo === 'prontas' && !atencao)) &&
        (!esconder || !copiada) &&
        (procurado === '' || (linha.dataset.busca || '').indexOf(procurado) !== -1);

      linha.hidden = !cabe;
      if (cabe) {
        visiveis += 1;
      }
    });

    Object.keys(contas).forEach(function (nome) {
      var alvo = barra.querySelector('[data-conta="' + nome + '"]');
      if (alvo) {
        alvo.textContent = contas[nome];
      }
    });

    var contagem = barra.querySelector('[data-contagem]');
    if (contagem) {
      contagem.textContent =
        visiveis === linhas.length ? '' : 'mostrando ' + visiveis + ' de ' + linhas.length;
    }

    var vazio = (tabela.closest('.cartao') || document).querySelector('.nenhuma-linha');
    if (vazio) {
      vazio.hidden = visiveis !== 0 || linhas.length === 0;
    }
  }

  function escolherChip(chip) {
    var barra = chip.closest('[data-filtros]');
    Array.prototype.forEach.call(barra.querySelectorAll('.chip'), function (outro) {
      var ligado = outro === chip;
      outro.classList.toggle('ativo', ligado);
      outro.setAttribute('aria-pressed', ligado ? 'true' : 'false');
    });
  }

  function tabelaDe(elemento) {
    var cartao = elemento.closest('.cartao') || document;
    return cartao.querySelector('[data-tabela]');
  }

  // -------------------------------------------------------------------- ligação

  function acha(alvo, seletor) {
    return alvo && alvo.closest ? alvo.closest(seletor) : null;
  }

  function preparar() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-tabela]'), function (tabela) {
      restaurar(tabela);
      filtrar(tabela);
    });
  }

  document.addEventListener('click', function (evento) {
    var botao = acha(evento.target, '[data-copiar]');
    if (botao) {
      evento.preventDefault();
      aoCopiar(botao);
      return;
    }

    var chip = acha(evento.target, '.chip[data-filtro]');
    if (chip) {
      escolherChip(chip);
      var tabela = tabelaDe(chip);
      if (tabela) {
        filtrar(tabela);
      }
    }
  });

  document.addEventListener('change', function (evento) {
    var caixinha = acha(evento.target, '[data-copiada]');
    if (caixinha) {
      aoMarcar(caixinha);
      return;
    }

    var alternador = acha(evento.target, '[data-ocultar-copiadas]');
    if (alternador) {
      var tabela = tabelaDe(alternador);
      if (tabela) {
        filtrar(tabela);
      }
    }
  });

  document.addEventListener('input', function (evento) {
    var busca = acha(evento.target, '[data-busca]');
    if (busca) {
      var tabela = tabelaDe(busca);
      if (tabela) {
        filtrar(tabela);
      }
    }
  });

  // Sem isto a marcação sumiria a cada troca do painel. Varre o documento
  // porque, num swap por `outerHTML`, o alvo do evento é o elemento antigo.
  document.body.addEventListener('htmx:afterSwap', preparar);

  preparar();
})();
