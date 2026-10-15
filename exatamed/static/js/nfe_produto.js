// Conferência da NF-e: cadastra o produto de um item não reconhecido sem sair da tela.
// O formulário do modal é preenchido com os dados do item (descrição, GTIN, registro ANVISA,
// unidade); ao salvar, o produto entra em todas as listas da nota e é escolhido no item.
(function () {
  const modal = document.getElementById('modal-produto');
  const formulario = document.getElementById('form-novo-produto');
  if (!modal || !formulario) return;
  const erros = document.getElementById('novo-erros');
  const salvar = document.getElementById('novo-salvar');
  const campo = function (nome) { return document.getElementById('novo_' + nome); };
  let itemAtual = null;

  function mostrarErros(lista) {
    erros.replaceChildren();
    lista.forEach(function (texto) {
      const linha = document.createElement('div');
      linha.textContent = texto;
      erros.appendChild(linha);
    });
    erros.classList.toggle('d-none', !lista.length);
  }

  modal.addEventListener('show.bs.modal', function (evento) {
    const botao = evento.relatedTarget;
    if (!botao) return;
    itemAtual = botao.dataset.item;
    formulario.reset();
    mostrarErros([]);
    document.getElementById('novo-item').textContent = itemAtual;
    document.getElementById('novo-descricao-nota').textContent = botao.dataset.descricao;
    campo('nome_comercial').value = botao.dataset.descricao || '';
    campo('gtin').value = botao.dataset.gtin || '';
    campo('registro_anvisa').value = botao.dataset.anvisa || '';
    const unidade = campo('unidade_medida');
    unidade.value = Array.from(unidade.options).some(function (o) { return o.value === botao.dataset.unidade; })
      ? botao.dataset.unidade : '';
    // O grupo de medicamento do XML traz o registro ANVISA; sem ele, provavelmente é material.
    campo('tipo').value = botao.dataset.anvisa ? 'MEDICAMENTO' : 'MATERIAL';
    const controle = campo('controle_especial');
    if (controle.reiniciarClassificacao) controle.reiniciarClassificacao();
  });

  modal.addEventListener('shown.bs.modal', function () { campo('principio_ativo').focus(); });

  formulario.addEventListener('submit', async function (evento) {
    evento.preventDefault();
    salvar.disabled = true;
    try {
      const resposta = await fetch(formulario.action, {
        method: 'POST', body: new FormData(formulario), headers: { 'Accept': 'application/json' },
      });
      const dados = (resposta.headers.get('Content-Type') || '').includes('json') ? await resposta.json() : {};
      if (resposta.status === 403) return mostrarErros(['Só o farmacêutico pode cadastrar produtos.']);
      if (!resposta.ok) return mostrarErros(dados.erros || ['Não foi possível salvar o produto.']);
      document.querySelectorAll('.produto-nfe').forEach(function (selecao) {
        const opcao = new Option(dados.texto, dados.id);
        opcao.dataset.unidade = dados.unidade;
        selecao.add(opcao);
      });
      const selecao = document.getElementById('produto_' + itemAtual);
      selecao.value = String(dados.id);
      selecao.dispatchEvent(new Event('change', { bubbles: true }));
      const dica = selecao.closest('div').querySelector('.dica-produto');
      if (dica) {
        dica.textContent = 'Produto cadastrado agora' + (dados.controle ? ' (controle especial ' + dados.controle + ')' : '') +
          '. Confira o fator de conversão.';
        dica.classList.add('text-success');
      }
      window.bootstrap.Modal.getInstance(modal).hide();
    } catch (erro) {
      mostrarErros(['Sem resposta do servidor. Tente de novo.']);
    } finally {
      salvar.disabled = false;
    }
  });
})();
