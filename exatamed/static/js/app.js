// Comportamentos comuns, sem JavaScript inline (exigência da política de segurança de conteúdo).
//   data-acao="imprimir"      -> imprime a página
//   data-confirmar="mensagem" -> pede confirmação antes de enviar o formulário ou seguir o clique
(function () {
  document.addEventListener('click', function (evento) {
    const imprimir = evento.target.closest('[data-acao="imprimir"]');
    if (imprimir) {
      evento.preventDefault();
      window.print();
      return;
    }
    const alvo = evento.target.closest('button[data-confirmar], a[data-confirmar]');
    if (alvo && !window.confirm(alvo.dataset.confirmar)) evento.preventDefault();
  });
  document.addEventListener('submit', function (evento) {
    const formulario = evento.target;
    if (formulario.dataset.confirmar && !window.confirm(formulario.dataset.confirmar)) evento.preventDefault();
  });
})();
