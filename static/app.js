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
      p.textContent = "Nenhum painel encontrado. Tente outro termo ou escolha um painel abaixo.";
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
(function () {
  var menus = Array.prototype.slice.call(document.querySelectorAll(".nav-grupo details, .menu-movel"));
  if (!menus.length) return;
  function fechar(menos) { menus.forEach(function (d) { if (d !== menos) d.open = false; }); }
  menus.forEach(function (d) {
    d.addEventListener("toggle", function () { if (d.open) fechar(d); });
    d.addEventListener("focusout", function (e) { if (d.open && e.relatedTarget && !d.contains(e.relatedTarget)) d.open = false; });
  });
  document.addEventListener("click", function (e) { if (!e.target.closest(".nav-grupo, .menu-movel")) fechar(null); });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var aberto = menus.filter(function (d) { return d.open; })[0];
    if (!aberto) return;
    aberto.open = false;
    aberto.querySelector("summary").focus();
  });
})();
(function () {
  // Tabelas largas rolam na horizontal: precisam ser alcançáveis pelo teclado e ter nome (WCAG 2.1.1, 4.1.2).
  document.querySelectorAll(".rolagem").forEach(function (r) {
    r.setAttribute("tabindex", "0");
    r.setAttribute("role", "region");
    var cap = r.querySelector("caption");
    r.setAttribute("aria-label", cap ? cap.textContent.trim() : "Tabela com rolagem horizontal");
  });
})();
(function () {
  var f = document.getElementById("inmetro-filtro");
  if (!f) return;
  f.hidden = false;
  var q = document.getElementById("inmetro-busca"), n = document.getElementById("inmetro-contagem"), espera = null;
  var linhas = Array.prototype.slice.call(document.querySelectorAll("#inmetro-tabela-invalidos tbody tr[data-busca], #inmetro-tabela-validos tbody tr[data-busca], #inmetro-tabela-antigos tbody tr[data-busca]"));
  function filtrar() {
    var t = q.value.trim().toLowerCase(), d = t.replace(/\D/g, ""), vistos = 0;
    linhas.forEach(function (l) { var ok = !t || l.dataset.busca.indexOf(t) !== -1 || (d.length >= 4 && d.length >= t.replace(/[\s.\-/]/g, "").length - 1 && l.dataset.digitos.indexOf(d) !== -1); l.hidden = !ok; if (ok) vistos++; });
    if (t) document.querySelectorAll("#inmetro-tabela-validos, #inmetro-tabela-antigos").forEach(function (tb) { var det = tb.closest("details"); if (det) det.open = true; });
    n.textContent = t ? (vistos ? vistos + " medidor(es) encontrado(s)" : "Nenhum medidor encontrado. Confira o número digitado e tente o portal oficial.") : "";
  }
  q.addEventListener("input", function () { clearTimeout(espera); espera = setTimeout(filtrar, 300); });
  f.addEventListener("submit", function (e) { e.preventDefault(); });
})();
(function () {
  var av = document.querySelector("[data-previsao-coleta]");
  if (!av) return;
  var coleta = Date.parse(av.dataset.previsaoColeta + "T12:00:00-03:00");
  if (!isNaN(coleta) && Date.now() - coleta > 2 * 86400000) av.hidden = false;
})();
