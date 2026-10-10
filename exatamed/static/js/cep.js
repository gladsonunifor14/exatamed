// Preenche logradouro, bairro, cidade e UF a partir do CEP, consultando o ViaCEP (https://viacep.com.br)
// direto do navegador. Os campos continuam editáveis: se a consulta falhar, basta
// preencher à mão. O "complemento" do ViaCEP descreve a faixa de numeração da rua
// (ex.: "lado ímpar"), não o complemento do endereço, por isso não é usado.
(function () {
  const cep = document.getElementById('cep');
  if (!cep) return;

  const campos = {
    logradouro: document.getElementById('logradouro'),
    bairro: document.getElementById('bairro'),
    cidade: document.getElementById('cidade'),
    uf: document.getElementById('uf'),
    numero: document.getElementById('numero'),
  };
  const aviso = document.createElement('div');
  aviso.className = 'form-text';
  aviso.id = 'cep-aviso';
  aviso.setAttribute('aria-live', 'polite');
  cep.closest('div').appendChild(aviso);

  let ultimoConsultado = '';

  function mostrar(texto, classe) {
    aviso.className = 'form-text ' + (classe || '');
    aviso.textContent = texto;
  }

  function mascarar() {
    const digitos = cep.value.replace(/\D/g, '').slice(0, 8);
    cep.value = digitos.length > 5 ? digitos.slice(0, 5) + '-' + digitos.slice(5) : digitos;
    return digitos;
  }

  async function consultar(digitos) {
    if (digitos === ultimoConsultado) return;
    ultimoConsultado = digitos;
    mostrar('Buscando endereço...', 'text-muted');
    const controle = new AbortController();
    const limite = setTimeout(() => controle.abort(), 8000);
    try {
      const resposta = await fetch('https://viacep.com.br/ws/' + digitos + '/json/', { signal: controle.signal });
      if (!resposta.ok) throw new Error('HTTP ' + resposta.status);
      const dados = await resposta.json();
      if (digitos !== cep.value.replace(/\D/g, '')) return;  // o CEP mudou durante a consulta
      if (dados.erro) {
        mostrar('CEP não encontrado. Confira o número ou preencha o endereço manualmente.', 'text-danger');
        return;
      }
      if (campos.logradouro) campos.logradouro.value = dados.logradouro || '';
      if (campos.bairro) campos.bairro.value = dados.bairro || '';
      if (campos.cidade) campos.cidade.value = dados.localidade || '';
      if (campos.uf) campos.uf.value = dados.uf || '';
      mostrar('Endereço preenchido pelo CEP. Confira e informe o número.', 'text-success');
      if (campos.numero) campos.numero.focus();
    } catch (erro) {
      ultimoConsultado = '';
      mostrar('Não foi possível consultar o CEP agora. Preencha o endereço manualmente.', 'text-warning-emphasis');
    } finally {
      clearTimeout(limite);
    }
  }

  cep.setAttribute('inputmode', 'numeric');
  cep.setAttribute('autocomplete', 'postal-code');
  cep.addEventListener('input', () => {
    const digitos = mascarar();
    if (digitos.length === 8) consultar(digitos);
    else if (aviso.textContent) mostrar('');
  });
})();
