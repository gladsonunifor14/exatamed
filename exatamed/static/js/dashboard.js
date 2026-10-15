// Dashboard: dica (tooltip) ao passar o mouse ou focar com o teclado uma marca dos gráficos.
// As marcas têm data-dica (e <title>, que funciona mesmo sem JavaScript).
(function () {
  const dica = document.getElementById('viz-dica');
  if (!dica) return;

  function mostrar(alvo, x, y) {
    dica.textContent = alvo.dataset.dica;
    dica.hidden = false;
    const largura = dica.offsetWidth;
    const altura = dica.offsetHeight;
    const esquerda = Math.min(Math.max(8, x - largura / 2), window.innerWidth - largura - 8);
    const topo = y - altura - 12 < 8 ? y + 16 : y - altura - 12;
    dica.style.left = esquerda + 'px';
    dica.style.top = topo + 'px';
  }

  function esconder() { dica.hidden = true; }

  document.addEventListener('pointermove', function (evento) {
    const alvo = evento.target.closest('[data-dica]');
    if (alvo) mostrar(alvo, evento.clientX, evento.clientY); else esconder();
  });
  document.addEventListener('focusin', function (evento) {
    const alvo = evento.target.closest('[data-dica]');
    if (!alvo) return esconder();
    const caixa = alvo.getBoundingClientRect();
    mostrar(alvo, caixa.left + caixa.width / 2, caixa.top);
  });
  document.addEventListener('focusout', esconder);
  document.addEventListener('scroll', esconder, true);
})();
