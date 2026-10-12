// Tela de dispensação: busca incremental de pacientes, avisos de alergia, controle especial
// e saldo por item. Todo texto vindo do cadastro é inserido com textContent (nunca innerHTML),
// para que conteúdo digitado em campos como "alergias" não seja interpretado como HTML.
(function () {
  const formulario = document.getElementById('form-dispensacao');
  if (!formulario) return;
  const tabela = document.querySelector('#itens tbody');
  const pacienteId = document.getElementById('paciente');
  const busca = document.getElementById('paciente-busca');
  const resultados = document.getElementById('paciente-resultados');
  const info = document.getElementById('info-paciente');
  const urlAlergias = formulario.dataset.urlAlergias;

  function elemento(tag, classe, texto, icone) {
    const el = document.createElement(tag);
    if (classe) el.className = classe;
    if (icone) {
      const i = document.createElement('i');
      i.className = 'bi ' + icone;
      el.appendChild(i);
      el.appendChild(document.createTextNode(' '));
    }
    if (texto) el.appendChild(document.createTextNode(texto));
    return el;
  }

  function mostrarInfoPaciente() {
    info.replaceChildren();
    if (!pacienteId.value) return;
    const alergias = pacienteId.dataset.alergias;
    info.appendChild(alergias
      ? elemento('span', 'text-danger', 'Alergias: ' + alergias, 'bi-exclamation-triangle-fill')
      : elemento('span', '', 'Sem alergias registradas.'));
  }

  // ---------------------------------------------------------------- busca de pacientes
  let temporizador = null;
  let consulta = 0;

  function fecharResultados() {
    resultados.hidden = true;
    busca.setAttribute('aria-expanded', 'false');
  }

  function escolher(paciente) {
    pacienteId.value = paciente.id;
    pacienteId.dataset.alergias = paciente.alergias || '';
    busca.value = paciente.nome;
    busca.setCustomValidity('');
    fecharResultados();
    mostrarInfoPaciente();
    verificarTodos();
  }

  async function pesquisar() {
    const termo = busca.value.trim();
    if (termo.length < 2) { fecharResultados(); return; }
    const minha = ++consulta;
    const resposta = await fetch(busca.dataset.url + '?q=' + encodeURIComponent(termo));
    if (!resposta.ok || minha !== consulta) return;
    const pacientes = await resposta.json();
    resultados.replaceChildren();
    if (!pacientes.length) {
      resultados.appendChild(elemento('div', 'list-group-item text-muted small', 'Nenhum paciente encontrado.'));
    }
    pacientes.forEach(function (p) {
      const item = elemento('button', 'list-group-item list-group-item-action');
      item.type = 'button';
      item.setAttribute('role', 'option');
      item.appendChild(elemento('div', 'fw-semibold', p.nome));
      const detalhes = [p.cpf ? 'CPF ' + p.cpf : null, p.nascimento ? 'Nasc. ' + p.nascimento : null, p.plano || 'SUS']
        .filter(Boolean).join(' · ');
      item.appendChild(elemento('div', 'small text-muted', detalhes));
      if (p.alergias) item.appendChild(elemento('div', 'small text-danger', 'Alergias: ' + p.alergias, 'bi-exclamation-triangle-fill'));
      item.addEventListener('click', function () { escolher(p); });
      resultados.appendChild(item);
    });
    resultados.hidden = false;
    busca.setAttribute('aria-expanded', 'true');
  }

  busca.addEventListener('input', function () {
    // Digitar de novo desfaz a escolha anterior: o paciente precisa ser selecionado na lista.
    pacienteId.value = '';
    busca.setCustomValidity('Selecione o paciente na lista de resultados.');
    mostrarInfoPaciente();
    clearTimeout(temporizador);
    temporizador = setTimeout(pesquisar, 250);
  });
  busca.addEventListener('keydown', function (evento) {
    if (evento.key === 'Enter') {
      evento.preventDefault();
      const primeiro = resultados.querySelector('button');
      if (!resultados.hidden && primeiro) primeiro.click();
    } else if (evento.key === 'Escape') {
      fecharResultados();
    }
  });
  document.addEventListener('click', function (evento) {
    if (!evento.target.closest('#paciente-resultados') && evento.target !== busca) fecharResultados();
  });

  // ---------------------------------------------------------------- avisos por item
  async function verificar(linha) {
    const produto = linha.querySelector('select').value;
    const aviso = linha.querySelector('.aviso');
    aviso.replaceChildren();
    if (!produto || !pacienteId.value) return;
    const resposta = await fetch(urlAlergias + '?paciente_id=' + encodeURIComponent(pacienteId.value) +
      '&produto_id=' + encodeURIComponent(produto));
    if (!resposta.ok) return;
    const dados = await resposta.json();
    const partes = [];
    if (dados.conflitos.length) partes.push(elemento('span', 'text-danger fw-semibold',
      'Conflito com alergia: ' + dados.conflitos.join(', '), 'bi-exclamation-octagon-fill'));
    if (dados.controlado) partes.push(elemento('span', 'text-warning-emphasis',
      'Controle especial (' + dados.controlado + ')', 'bi-shield-lock'));
    const origem = formulario.querySelector('[name=origem_id]').value;
    if (origem && dados.saldos) partes.push(elemento('span', 'text-muted', 'Saldo na origem: ' + dados.saldos[origem]));
    partes.forEach(function (parte, indice) {
      if (indice) aviso.appendChild(document.createTextNode(' · '));
      aviso.appendChild(parte);
    });
  }

  function verificarTodos() { tabela.querySelectorAll('tr.item').forEach(verificar); }

  tabela.addEventListener('change', function (e) { if (e.target.tagName === 'SELECT') verificar(e.target.closest('tr')); });
  tabela.addEventListener('click', function (e) {
    const botao = e.target.closest('.remover');
    if (!botao) return;
    if (tabela.querySelectorAll('tr.item').length > 1) botao.closest('tr').remove();
    else botao.closest('tr').querySelectorAll('select, input').forEach(function (el) { el.value = ''; });
  });
  document.getElementById('adicionar').addEventListener('click', function () {
    const nova = tabela.querySelector('tr.item').cloneNode(true);
    nova.querySelectorAll('select, input').forEach(function (el) { el.value = ''; });
    nova.querySelector('.aviso').replaceChildren();
    tabela.appendChild(nova);
  });
  formulario.querySelector('[name=origem_id]').addEventListener('change', verificarTodos);
  if (!pacienteId.value && busca.value) busca.value = '';
  mostrarInfoPaciente();
  verificarTodos();
})();
