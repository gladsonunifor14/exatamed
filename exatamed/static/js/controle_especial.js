// Preenche o controle especial (Portaria 344/98, RDC 471/2021) a partir do princípio ativo.
// Cada <select data-classificar="id1,id2"> é classificado pelo texto desses campos, consultando
// a tabela de referência no servidor. A escolha manual do farmacêutico prevalece; o servidor
// repete a classificação ao salvar.
(function () {
  const url = document.currentScript && document.currentScript.dataset.url;
  if (!url) return;

  document.querySelectorAll('select[data-classificar]').forEach(function (selecao) {
    const ids = selecao.dataset.classificar.split(',');
    const fontes = ids.map(function (id) { return document.getElementById(id.trim()); }).filter(Boolean);
    if (!fontes.length) return;
    const aviso = document.createElement('div');
    aviso.className = 'form-text text-success';
    aviso.setAttribute('aria-live', 'polite');
    selecao.closest('div').appendChild(aviso);
    // Automático enquanto o campo estiver vazio ou tiver sido preenchido por esta classificação.
    let automatico = !selecao.value;
    let espera = null;
    let pedido = 0;

    selecao.addEventListener('change', function () {
      automatico = false;
      aviso.textContent = '';
    });

    async function classificar() {
      if (!automatico) return;
      const numero = ++pedido;
      const parametros = new URLSearchParams();
      parametros.set('principio_ativo', fontes[0].value);
      if (fontes[1]) parametros.set('nome_comercial', fontes[1].value);
      try {
        const resposta = await fetch(url + '?' + parametros.toString(), { headers: { 'Accept': 'application/json' } });
        if (!resposta.ok || numero !== pedido || !automatico) return;
        const dados = await resposta.json();
        selecao.value = dados.lista || '';
        aviso.textContent = dados.lista
          ? 'Classificado automaticamente: ' + dados.substancia + ' — ' + dados.rotulo + ' (' + dados.referencia + '). Confira.'
          : '';
      } catch (erro) {
        // Sem resposta: o servidor classifica ao salvar.
      }
    }

    fontes.forEach(function (campo) {
      campo.addEventListener('input', function () {
        clearTimeout(espera);
        espera = setTimeout(classificar, 300);
      });
    });
    // Usado quando o formulário é reaproveitado (cadastro de produto na conferência da NF-e).
    selecao.reiniciarClassificacao = function () {
      automatico = true;
      selecao.value = '';
      aviso.textContent = '';
      classificar();
    };
  });
})();
