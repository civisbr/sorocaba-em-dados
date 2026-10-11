(function () {
  "use strict";
  var svg = document.getElementById("mapa-saude");
  if (!svg) return;
  var NS = "http://www.w3.org/2000/svg";
  var quadro = svg.parentNode;
  var vb = svg.getAttribute("viewBox").split(" ").map(Number);
  var W = vb[2], H = vb[3];
  var afim = { k: +svg.dataset.k, escala: +svg.dataset.escala, dx: +svg.dataset.dx, dy: +svg.dataset.dy };
  var caixa = svg.dataset.caixa.split(",").map(Number); // sul, oeste, norte, leste
  var view = { x: 0, y: 0, w: W, h: H };
  var unidades = Array.prototype.slice.call(svg.querySelectorAll(".ms-u"));
  var dica = document.getElementById("mapa-dica");
  var painelSel = document.getElementById("ms-selecionada");
  var painelProx = document.getElementById("ms-proximas");
  var msg = document.getElementById("ms-msg");
  var gVoce = document.getElementById("ms-voce");
  var gAneis = document.getElementById("ms-aneis");
  var posicao = null;
  var NOMES = { hospital: "Hospital", upa: "UPA ou pronto atendimento", ubs: "Unidade básica de saúde", caps: "CAPS (saúde mental)" };

  document.querySelectorAll("[data-so-js]").forEach(function (e) { e.hidden = false; });
  svg.querySelectorAll(".ms-u > title").forEach(function (t) { t.parentNode.removeChild(t); }); // a dica própria substitui a nativa

  function limitar() {
    view.w = Math.min(Math.max(view.w, W / 14), W);
    view.h = view.w * (H / W);
    view.x = Math.min(Math.max(view.x, 0), W - view.w);
    view.y = Math.min(Math.max(view.y, 0), H - view.h);
  }
  function aplicar() {
    limitar();
    svg.setAttribute("viewBox", view.x.toFixed(1) + " " + view.y.toFixed(1) + " " + view.w.toFixed(1) + " " + view.h.toFixed(1));
    var k = view.w / (svg.getBoundingClientRect().width || W);
    svg.style.setProperty("--k", k.toFixed(4));
    quadro.classList.toggle("ms-longe", view.w > W / 2.2);
  }
  function paraSvg(cx, cy) {
    var r = svg.getBoundingClientRect();
    return { x: view.x + (cx - r.left) / r.width * view.w, y: view.y + (cy - r.top) / r.height * view.h };
  }
  function zoom(f, p) {
    p = p || { x: view.x + view.w / 2, y: view.y + view.h / 2 };
    var nw = Math.min(Math.max(view.w * f, W / 14), W), real = nw / view.w;
    view.x = p.x - (p.x - view.x) * real;
    view.y = p.y - (p.y - view.y) * real;
    view.w = nw;
    aplicar();
  }
  function enquadrar(pts, folga) {
    var xs = pts.map(function (p) { return p.x; }), ys = pts.map(function (p) { return p.y; });
    var minx = Math.min.apply(null, xs), maxx = Math.max.apply(null, xs), miny = Math.min.apply(null, ys), maxy = Math.max.apply(null, ys);
    var w = Math.max(maxx - minx, maxy - miny, 90) * (1 + (folga || 0.5));
    view.w = w; view.x = (minx + maxx) / 2 - w / 2; view.y = (miny + maxy) / 2 - w * (H / W) / 2;
    aplicar();
  }
  function ponto(el) { var t = el.getAttribute("transform").match(/translate\(([-\d.]+) ([-\d.]+)\)/); return { x: +t[1], y: +t[2] }; }

  // arrastar e pinçar
  var ptrs = {}, ultimoDist = 0, arrastou = false;
  svg.addEventListener("pointerdown", function (e) {
    ptrs[e.pointerId] = { x: e.clientX, y: e.clientY };
    arrastou = false;
    if (Object.keys(ptrs).length === 2) { var a = Object.keys(ptrs).map(function (i) { return ptrs[i]; }); ultimoDist = Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y); }
  });
  svg.addEventListener("pointermove", function (e) {
    var p = ptrs[e.pointerId];
    if (!p) return;
    var n = Object.keys(ptrs).length;
    if (n === 1) {
      var r = svg.getBoundingClientRect(), dx = e.clientX - p.x, dy = e.clientY - p.y;
      if (!arrastou && Math.hypot(dx, dy) < 4) return;
      if (!arrastou) { arrastou = true; svg.setPointerCapture(e.pointerId); svg.classList.add("ms-arrastando"); esconderDica(); }
      view.x -= dx / r.width * view.w; view.y -= dy / r.height * view.h;
      p.x = e.clientX; p.y = e.clientY;
      aplicar();
    } else if (n === 2) {
      ptrs[e.pointerId] = { x: e.clientX, y: e.clientY };
      var a = Object.keys(ptrs).map(function (i) { return ptrs[i]; }), d = Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y);
      if (ultimoDist) zoom(ultimoDist / d, paraSvg((a[0].x + a[1].x) / 2, (a[0].y + a[1].y) / 2));
      ultimoDist = d; arrastou = true;
    }
  });
  function soltar(e) { delete ptrs[e.pointerId]; ultimoDist = 0; svg.classList.remove("ms-arrastando"); }
  svg.addEventListener("pointerup", soltar);
  svg.addEventListener("pointercancel", soltar);
  svg.addEventListener("wheel", function (e) {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    zoom(e.deltaY > 0 ? 1.2 : 1 / 1.2, paraSvg(e.clientX, e.clientY));
  }, { passive: false });
  svg.addEventListener("dblclick", function (e) { zoom(0.5, paraSvg(e.clientX, e.clientY)); });
  quadro.addEventListener("keydown", function (e) {
    if (e.target !== svg && e.target !== quadro) return;
    var passo = view.w * 0.12;
    var acoes = { ArrowLeft: function () { view.x -= passo; }, ArrowRight: function () { view.x += passo; }, ArrowUp: function () { view.y -= passo; }, ArrowDown: function () { view.y += passo; }, "+": function () { zoom(0.7); }, "=": function () { zoom(0.7); }, "-": function () { zoom(1 / 0.7); } };
    if (acoes[e.key]) { e.preventDefault(); acoes[e.key](); aplicar(); }
  });
  document.getElementById("ms-mais").addEventListener("click", function () { zoom(0.6); });
  document.getElementById("ms-menos").addEventListener("click", function () { zoom(1 / 0.6); });
  document.getElementById("ms-tudo").addEventListener("click", function () { view = { x: 0, y: 0, w: W, h: H }; aplicar(); });
  window.addEventListener("resize", aplicar);

  // dica e seleção
  function dist(u) { return u.dataset.dist ? " · a " + fmtKm(+u.dataset.dist) + " de você" : ""; }
  function fmtKm(m) { return m < 1000 ? Math.round(m / 10) * 10 + " m" : (m / 1000).toFixed(1).replace(".", ",") + " km"; }
  function mostrarDica(u) {
    dica.textContent = "";
    var b = document.createElement("strong"); b.textContent = u.dataset.nome; dica.appendChild(b);
    var s = document.createElement("span"); s.textContent = NOMES[u.dataset.grupo] + dist(u); dica.appendChild(s);
    dica.hidden = false;
    var r = u.getBoundingClientRect(), q = quadro.getBoundingClientRect();
    var x = r.left - q.left + r.width / 2, y = r.top - q.top;
    dica.style.left = Math.min(Math.max(x, 90), q.width - 90) + "px";
    dica.style.top = (y < 70 ? y + r.height + 8 : y - 8) + "px";
    dica.classList.toggle("abaixo", y < 70);
  }
  function esconderDica() { dica.hidden = true; }
  function linha(rotulo, valor) { var d = document.createElement("div"), t = document.createElement("dt"), v = document.createElement("dd"); t.textContent = rotulo; v.textContent = valor; d.appendChild(t); d.appendChild(v); return d; }
  function selecionar(u) {
    unidades.forEach(function (x) { x.classList.toggle("ms-sel", x === u); });
    u.parentNode.appendChild(u);
    painelSel.textContent = "";
    var h = document.createElement("h3"); h.textContent = u.dataset.nome; painelSel.appendChild(h);
    var dl = document.createElement("dl"); dl.className = "ms-dl";
    dl.appendChild(linha("Tipo", NOMES[u.dataset.grupo] + (u.dataset.natureza ? " · " + u.dataset.natureza : "")));
    if (u.dataset.sus) dl.appendChild(linha("SUS", u.dataset.sus));
    if (u.dataset.endereco) dl.appendChild(linha("Endereço", u.dataset.endereco));
    if (u.dataset.telefone) dl.appendChild(linha("Telefone", u.dataset.telefone));
    if (u.dataset.dist) dl.appendChild(linha("Distância em linha reta", fmtKm(+u.dataset.dist)));
    painelSel.appendChild(dl);
    var a = document.createElement("a");
    a.rel = "noopener noreferrer"; a.className = "ms-link";
    var la = u.dataset.lat, lo = u.dataset.lon;
    a.href = "https://www.openstreetmap.org/" + (posicao ? "directions?from=" + posicao.lat.toFixed(5) + "," + posicao.lon.toFixed(5) + "&to=" + la + "," + lo : "?mlat=" + la + "&mlon=" + lo + "#map=17/" + la + "/" + lo);
    a.textContent = posicao ? "Como chegar (abre o OpenStreetMap)" : "Ver no OpenStreetMap";
    painelSel.appendChild(a);
  }
  unidades.forEach(function (u) {
    u.addEventListener("mouseenter", function () { if (!arrastou) mostrarDica(u); });
    u.addEventListener("mouseleave", esconderDica);
    u.addEventListener("focus", function () { mostrarDica(u); });
    u.addEventListener("blur", esconderDica);
    u.addEventListener("click", function (e) { e.stopPropagation(); if (!arrastou) selecionar(u); });
    u.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selecionar(u); } });
    u.addEventListener("pointerdown", function (e) { e.stopPropagation(); });
  });

  // filtro por tipo
  document.querySelectorAll(".ms-filtro input").forEach(function (c) {
    c.addEventListener("change", function () {
      unidades.forEach(function (u) { if (u.dataset.grupo === c.value) u.classList.toggle("ms-off", !c.checked); });
      if (posicao) listarProximas();
    });
  });
  function visivel(u) { return !u.classList.contains("ms-off"); }

  // localização
  function metros(la1, lo1, la2, lo2) {
    var R = 6371000, r = Math.PI / 180, dla = (la2 - la1) * r, dlo = (lo2 - lo1) * r;
    var a = Math.sin(dla / 2) * Math.sin(dla / 2) + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dlo / 2) * Math.sin(dlo / 2);
    return 2 * R * Math.asin(Math.sqrt(a));
  }
  function xy(lat, lon) { return { x: lon * afim.k * afim.escala + afim.dx, y: -lat * afim.escala + afim.dy }; }
  function elem(nome, attrs) { var e = document.createElementNS(NS, nome); Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); }); return e; }
  function aviso(t) { msg.textContent = t; }
  function marcar(lat, lon, rotulo) {
    if (lat < caixa[0] - 0.04 || lat > caixa[2] + 0.04 || lon < caixa[1] - 0.04 || lon > caixa[3] + 0.04) {
      aviso("Esse ponto fica fora de Sorocaba, então não mostro distâncias.");
      return;
    }
    posicao = { lat: lat, lon: lon };
    var p = xy(lat, lon), upm = afim.escala / 111320;
    gAneis.textContent = ""; gVoce.textContent = "";
    [1000, 2000, 5000].forEach(function (m) {
      gAneis.appendChild(elem("circle", { cx: p.x, cy: p.y, r: m * upm, class: "ms-anel" }));
      var t = elem("text", { x: p.x, y: p.y - m * upm, class: "ms-anel-t", "text-anchor": "middle" }); t.textContent = m / 1000 + " km"; gAneis.appendChild(t);
    });
    var g = elem("g", { transform: "translate(" + p.x.toFixed(1) + " " + p.y.toFixed(1) + ")" });
    g.appendChild(elem("circle", { r: 15, class: "ms-voce-halo" }));
    g.appendChild(elem("circle", { r: 7, class: "ms-voce-ponto" }));
    gVoce.appendChild(g);
    gVoce.removeAttribute("hidden");
    unidades.forEach(function (u) { u.dataset.dist = Math.round(metros(lat, lon, +u.dataset.lat, +u.dataset.lon)); });
    aviso("Posição marcada: " + rotulo + ". Fica só no seu navegador; nada é enviado.");
    listarProximas();
  }
  function listarProximas() {
    painelProx.textContent = "";
    var titulo = document.createElement("h3"); titulo.textContent = "Mais perto de você"; painelProx.appendChild(titulo);
    var ul = document.createElement("ul"); ul.className = "ms-prox";
    var achou = [];
    ["hospital", "upa", "ubs", "caps"].forEach(function (g) {
      var lista = unidades.filter(function (u) { return u.dataset.grupo === g && visivel(u); }).sort(function (a, b) { return a.dataset.dist - b.dataset.dist; });
      if (!lista.length) return;
      var u = lista[0];
      achou.push(ponto(u));
      var li = document.createElement("li"), b = document.createElement("button");
      b.type = "button"; b.className = "ms-prox-b";
      var tipo = document.createElement("span"); tipo.className = "ms-prox-t"; tipo.textContent = NOMES[g];
      var nome = document.createElement("strong"); nome.textContent = u.dataset.nome;
      var d = document.createElement("span"); d.className = "ms-prox-d"; d.textContent = fmtKm(+u.dataset.dist) + " em linha reta";
      b.appendChild(tipo); b.appendChild(nome); b.appendChild(d);
      b.addEventListener("click", function () { selecionar(u); var p = ponto(u), q = xy(posicao.lat, posicao.lon); enquadrar([p, q], 0.6); });
      li.appendChild(b); ul.appendChild(li);
    });
    painelProx.appendChild(ul);
    var nota = document.createElement("p"); nota.className = "pequeno suave"; nota.textContent = "Distância em linha reta, não pelo caminho. Em emergência, ligue 192 (SAMU).";
    painelProx.appendChild(nota);
    painelProx.hidden = false;
    if (achou.length) enquadrar(achou.concat([xy(posicao.lat, posicao.lon)]), 0.35);
  }
  var btnGps = document.getElementById("ms-gps");
  btnGps.addEventListener("click", function () {
    if (!navigator.geolocation) { aviso("Seu navegador não informa a localização. Escolha o bairro."); return; }
    aviso("Procurando sua posição…");
    btnGps.disabled = true;
    navigator.geolocation.getCurrentPosition(function (p) {
      btnGps.disabled = false;
      marcar(p.coords.latitude, p.coords.longitude, "sua localização" + (p.coords.accuracy > 1500 ? " (aproximada)" : ""));
    }, function (err) {
      btnGps.disabled = false;
      aviso(err.code === 1 ? "A localização foi negada. Escolha o bairro ao lado." : "Não consegui sua posição. Escolha o bairro ao lado.");
    }, { enableHighAccuracy: false, timeout: 12000, maximumAge: 60000 });
  });

  // bairro como alternativa, sem permissão de localização
  var campo = document.getElementById("ms-bairro"), lista = document.getElementById("ms-bairros"), bairros = null;
  function norm(s) { return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").trim(); }
  function carregar() {
    if (bairros) return;
    bairros = [];
    fetch(svg.dataset.bairros).then(function (r) { return r.json(); }).then(function (d) {
      bairros = d;
      var visto = {};
      d.forEach(function (b) { if (visto[b.n]) return; visto[b.n] = 1; var o = document.createElement("option"); o.value = b.n; lista.appendChild(o); });
    }).catch(function () { bairros = null; aviso("Não consegui carregar a lista de bairros."); });
  }
  campo.addEventListener("focus", carregar);
  campo.addEventListener("input", carregar);
  document.getElementById("ms-bairro-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var q = norm(campo.value);
    var b = (bairros || []).filter(function (x) { return norm(x.n) === q; })[0] || (q.length > 2 ? (bairros || []).filter(function (x) { return norm(x.n).indexOf(q) !== -1; })[0] : null);
    if (!b) { aviso("Não achei esse bairro. Escolha um da lista."); return; }
    marcar(b.la, b.lo, "centro do bairro " + b.n + ", aproximado");
  });
  svg.addEventListener("click", function () { esconderDica(); });
  aplicar();
})();
