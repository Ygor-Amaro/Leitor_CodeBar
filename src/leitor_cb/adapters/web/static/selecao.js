/* Recorte da página com o mouse — o `cv2.selectROI` da CLI, só que no
 * navegador: lá a janela abriria na máquina do servidor.
 *
 * Não envia nada; escreve as coordenadas nos campos escondidos e quem faz o
 * POST é o HTMX.
 */
(function () {
  'use strict';

  var palco = document.getElementById('palco');
  if (!palco) {
    return;
  }

  var imagem = document.getElementById('imagem-pagina');
  var retangulo = document.getElementById('retangulo');
  var medida = document.getElementById('medida');

  var campos = {
    x: document.getElementById('campo-x'),
    y: document.getElementById('campo-y'),
    largura: document.getElementById('campo-largura'),
    altura: document.getElementById('campo-altura')
  };

  var arrastando = false;
  var inicio = { x: 0, y: 0 };

  // A imagem é exibida reduzida, mas o servidor recorta em pixels da página
  // rasterizada: sem a escala, o retângulo apontaria para outro pedaço.
  function escala() {
    if (!imagem.clientWidth) {
      return 1;
    }
    return imagem.naturalWidth / imagem.clientWidth;
  }

  function posicao(evento) {
    var caixa = imagem.getBoundingClientRect();
    return {
      x: Math.min(Math.max(evento.clientX - caixa.left, 0), caixa.width),
      y: Math.min(Math.max(evento.clientY - caixa.top, 0), caixa.height)
    };
  }

  function desenhar(de, ate) {
    var esquerda = Math.min(de.x, ate.x);
    var topo = Math.min(de.y, ate.y);
    var largura = Math.abs(de.x - ate.x);
    var altura = Math.abs(de.y - ate.y);

    retangulo.style.left = esquerda + 'px';
    retangulo.style.top = topo + 'px';
    retangulo.style.width = largura + 'px';
    retangulo.style.height = altura + 'px';
    retangulo.hidden = false;

    var fator = escala();
    campos.x.value = Math.round(esquerda * fator);
    campos.y.value = Math.round(topo * fator);
    campos.largura.value = Math.round(largura * fator);
    campos.altura.value = Math.round(altura * fator);

    if (medida) {
      if (largura < 5 || altura < 5) {
        medida.textContent = 'arraste um pouco mais para marcar a área';
      } else {
        medida.textContent =
          'área marcada: ' + campos.largura.value + ' × ' + campos.altura.value + ' px';
      }
    }
  }

  // Largura e altura zeradas são o combinado para "página inteira": é como o
  // botão ao lado funciona sem rota própria.
  function limpar() {
    retangulo.hidden = true;
    campos.largura.value = 0;
    campos.altura.value = 0;
    if (medida) {
      medida.textContent = '';
    }
  }

  imagem.addEventListener('pointerdown', function (evento) {
    evento.preventDefault(); // impede o arrasto nativo de imagem do navegador
    arrastando = true;
    inicio = posicao(evento);
    imagem.setPointerCapture(evento.pointerId);
    desenhar(inicio, inicio);
  });

  imagem.addEventListener('pointermove', function (evento) {
    if (arrastando) {
      desenhar(inicio, posicao(evento));
    }
  });

  imagem.addEventListener('pointerup', function (evento) {
    if (!arrastando) {
      return;
    }
    arrastando = false;
    imagem.releasePointerCapture(evento.pointerId);
    desenhar(inicio, posicao(evento));
  });

  var lerPaginaInteira = document.getElementById('ler-pagina');
  if (lerPaginaInteira) {
    lerPaginaInteira.addEventListener('click', limpar);
  }

  document.addEventListener('keydown', function (evento) {
    if (evento.key === 'Escape') {
      limpar();
    }
  });
})();
