// Modo claro/escuro. Carregado no <head>, antes do conteúdo, para a página já abrir na cor certa.
// A preferência do usuário vem em <html data-tema>: "claro", "escuro" ou "sistema" (segue o aparelho).
// Na impressão a página volta ao modo claro.
(function () {
  const raiz = document.documentElement;
  const tema = raiz.dataset.tema || 'sistema';
  const aparelho = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function aplicar() {
    const escuro = tema === 'escuro' || (tema === 'sistema' && aparelho && aparelho.matches);
    raiz.setAttribute('data-bs-theme', escuro ? 'dark' : 'light');
  }

  aplicar();
  if (aparelho && tema === 'sistema' && aparelho.addEventListener) aparelho.addEventListener('change', aplicar);
  window.addEventListener('beforeprint', function () { raiz.setAttribute('data-bs-theme', 'light'); });
  window.addEventListener('afterprint', aplicar);
})();
