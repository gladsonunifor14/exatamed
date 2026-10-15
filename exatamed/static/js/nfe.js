// Conferência da NF-e: mostra, para cada lote, quanto entra no estoque (quantidade da
// nota x fator) e o custo por unidade do estoque (custo da nota ÷ fator). O cálculo
// definitivo é refeito no servidor; aqui é só pré-visualização.
(function () {
  const formatar = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 4 });
  const moeda = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 4 });

  function numero(texto) {
    const limpo = String(texto || '').trim().replace(/\./g, (texto || '').includes(',') ? '' : '.').replace(',', '.');
    const valor = parseFloat(limpo);
    return isNaN(valor) ? null : valor;
  }

  function atualizar(card) {
    const fator = numero(card.querySelector('.fator-nfe') && card.querySelector('.fator-nfe').value);
    const selecao = card.querySelector('.produto-nfe');
    const opcao = selecao && selecao.selectedOptions[0];
    const unidade = opcao && opcao.dataset.unidade ? opcao.dataset.unidade : '';
    const custoNota = numero(card.dataset.custo);
    const custo = card.querySelector('.custo-estoque');
    if (custo) {
      custo.textContent = fator && fator > 0 && custoNota !== null
        ? 'Custo no estoque: ' + moeda.format(custoNota / fator) + (unidade ? ' / ' + unidade : '') : '';
    }
    card.querySelectorAll('.lote-nfe').forEach(function (linha) {
      const destino = linha.querySelector('.quantidade-estoque');
      const quantidade = numero(linha.dataset.quantidade);
      destino.textContent = fator && fator > 0 && quantidade !== null
        ? formatar.format(quantidade * fator) + (unidade ? ' ' + unidade : '') : '—';
    });
  }

  document.querySelectorAll('.item-nfe').forEach(function (card) {
    card.addEventListener('input', function () { atualizar(card); });
    card.addEventListener('change', function () { atualizar(card); });
    atualizar(card);
  });
})();
