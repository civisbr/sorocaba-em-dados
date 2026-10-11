(function () {
  var f = document.getElementById("escolas-filtro");
  if (!f) return;
  f.hidden = false;
  var q = document.getElementById("busca-escola"), rede = document.getElementById("rede"), n = document.getElementById("escolas-contagem");
  var itens = Array.prototype.slice.call(document.querySelectorAll("#lista-escolas li"));
  function norm(s) { return s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, ""); }
  function filtrar() {
    var t = norm(q.value.trim()), r = rede.value, vistos = 0;
    itens.forEach(function (li) {
      var ok = (!t || norm(li.textContent).indexOf(t) !== -1) && (!r || li.dataset.rede === r);
      li.hidden = !ok;
      if (ok) vistos++;
    });
    n.textContent = (t || r) ? vistos + " de " + itens.length + " escolas" : "";
  }
  q.addEventListener("input", filtrar);
  rede.addEventListener("change", filtrar);
  f.addEventListener("submit", function (e) { e.preventDefault(); });
})();
(function () {
  var form = document.getElementById("busca-form");
  if (!form) return;
  form.hidden = false;
  var input = document.getElementById("busca-q");
  var saida = document.getElementById("busca-resultados");
  var indice = Array.prototype.slice.call(document.querySelectorAll("#busca-indice a"));
  function normaliza(s) {
    return s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }
  function buscar() {
    var q = normaliza(input.value.trim());
    saida.textContent = "";
    if (!q) return;
    var achados = indice.filter(function (a) {
      return q.length >= 3 && normaliza(a.dataset.palavras).split(" ").filter(function (k) { return k.length > 2; }).some(function (k) { return k.indexOf(q) !== -1 || q.indexOf(k) !== -1 && k.length > 2; });
    });
    if (!achados.length) {
      var p = document.createElement("p");
      p.textContent = "Nenhum painel encontrado. Por enquanto a busca encontra os painéis de Emprego, Combustível e Escolas.";
      saida.appendChild(p);
      return;
    }
    var ul = document.createElement("ul");
    achados.forEach(function (a) {
      var li = document.createElement("li");
      li.appendChild(a.cloneNode(true));
      ul.appendChild(li);
    });
    saida.appendChild(ul);
  }
  input.addEventListener("input", buscar);
  form.addEventListener("submit", function (e) { e.preventDefault(); });
})();
