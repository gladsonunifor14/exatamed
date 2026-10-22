// Comportamentos comuns, sem JavaScript inline (exigência da política de segurança de conteúdo).
//   data-acao="imprimir"      -> imprime a página
//   data-confirmar="mensagem" -> pede confirmação (janela do sistema) antes de enviar o formulário
//                                ou seguir o clique. Opcionais: data-confirmar-titulo,
//                                data-confirmar-botao (texto do botão) e data-confirmar-perigo
//                                (botão vermelho, para exclusões e ações sem volta).
//   .toast                    -> avisos depois de salvar, que somem sozinhos
(function () {
  const liberados = new WeakSet();  // elementos já confirmados: o próximo clique/envio segue normalmente
  let janela = null;
  let aoConfirmar = null;

  function criarJanela() {
    const div = document.createElement('div');
    div.className = 'modal fade';
    div.id = 'modal-confirmacao';
    div.tabIndex = -1;
    div.setAttribute('aria-labelledby', 'modal-confirmacao-titulo');
    div.setAttribute('aria-hidden', 'true');
    div.innerHTML =
      '<div class="modal-dialog modal-dialog-centered"><div class="modal-content">' +
      '<div class="modal-header"><h2 class="modal-title fs-5" id="modal-confirmacao-titulo"></h2>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fechar"></button></div>' +
      '<div class="modal-body"><p class="mb-0 confirmacao-mensagem"></p></div>' +
      '<div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>' +
      '<button type="button" class="btn confirmacao-ok"></button></div>' +
      '</div></div>';
    document.body.appendChild(div);
    div.querySelector('.confirmacao-ok').addEventListener('click', function () {
      const acao = aoConfirmar;
      aoConfirmar = null;
      bootstrap.Modal.getOrCreateInstance(div).hide();
      if (acao) acao();
    });
    div.addEventListener('shown.bs.modal', function () { div.querySelector('.confirmacao-ok').focus(); });
    div.addEventListener('hidden.bs.modal', function () { aoConfirmar = null; });
    return div;
  }

  function confirmar(origem, acao) {
    const mensagem = origem.dataset.confirmar;
    if (!window.bootstrap || !bootstrap.Modal) {
      if (window.confirm(mensagem)) acao();
      return;
    }
    janela = janela || criarJanela();
    const perigo = origem.hasAttribute('data-confirmar-perigo');
    janela.querySelector('.modal-title').textContent = origem.dataset.confirmarTitulo || 'Confirmar ação';
    janela.querySelector('.confirmacao-mensagem').textContent = mensagem;
    const ok = janela.querySelector('.confirmacao-ok');
    ok.textContent = origem.dataset.confirmarBotao || 'Confirmar';
    ok.className = 'btn confirmacao-ok ' + (perigo ? 'btn-danger' : 'btn-exata');
    aoConfirmar = acao;
    bootstrap.Modal.getOrCreateInstance(janela).show();
  }

  document.addEventListener('click', function (evento) {
    const imprimir = evento.target.closest('[data-acao="imprimir"]');
    if (imprimir) {
      evento.preventDefault();
      window.print();
      return;
    }
    const alvo = evento.target.closest('button[data-confirmar], a[data-confirmar]');
    if (!alvo) return;
    if (liberados.has(alvo)) {
      liberados.delete(alvo);
      return;
    }
    evento.preventDefault();
    confirmar(alvo, function () {
      liberados.add(alvo);
      alvo.click();
    });
  });

  document.addEventListener('submit', function (evento) {
    const formulario = evento.target;
    if (!formulario.dataset.confirmar) return;
    if (liberados.has(formulario)) {
      liberados.delete(formulario);
      return;
    }
    evento.preventDefault();
    const botao = evento.submitter;
    confirmar(formulario, function () {
      liberados.add(formulario);
      if (formulario.requestSubmit) formulario.requestSubmit(botao || undefined);
      else formulario.submit();
    });
  });

  document.addEventListener('DOMContentLoaded', function () {
    if (!window.bootstrap || !bootstrap.Toast) return;
    document.querySelectorAll('.avisos .toast').forEach(function (aviso) {
      bootstrap.Toast.getOrCreateInstance(aviso).show();
    });
  });
})();
