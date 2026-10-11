(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  Array.prototype.slice.call(document.querySelectorAll(".mapa-interativo")).forEach(iniciar);

  function iniciar(raiz) {
    var svg = raiz.querySelector(".ms-svg");
    if (!svg) return;
    function q(c) { return raiz.querySelector(c); }
    var quadro = svg.parentNode;
    var vb = svg.getAttribute("viewBox").split(" ").map(Number);
    var W = vb[2], H = vb[3];
    var vistaInicial = { x: vb[0], y: vb[1], w: vb[2], h: vb[3] };
    var QUADRO_W = +svg.dataset.largura || W, QUADRO_H = +svg.dataset.altura || H;
    var afim = { k: +svg.dataset.k, escala: +svg.dataset.escala, dx: +svg.dataset.dx, dy: +svg.dataset.dy };
    var NOMES = JSON.parse(svg.dataset.nomes || "{}");
    var ORDEM = (svg.dataset.ordem || "").split(",").filter(Boolean);
    var NOTA = svg.dataset.nota || "";
    var view = { x: vb[0], y: vb[1], w: vb[2], h: vb[3] };
    var unidades = Array.prototype.slice.call(svg.querySelectorAll(".ms-u"));
    var celulas = Array.prototype.slice.call(svg.querySelectorAll(".ms-c"));
    var dica = q(".ms-dica"), painelSel = q(".ms-selecionada"), painelProx = q(".ms-proximas"), msg = q(".ms-msg");
    var gVoce = q(".ms-voce"), gAneis = q(".ms-aneis");
    var atual = null, posicao = null, distancias = new Map();

    raiz.querySelectorAll("[data-so-js]").forEach(function (e) { e.hidden = false; });
    raiz.querySelectorAll("[data-sem-js]").forEach(function (e) { e.hidden = true; });
    unidades.forEach(function (u) { u.setAttribute("tabindex", "0"); u.setAttribute("role", "button"); });
    svg.querySelectorAll(".ms-u > title, .ms-c > title").forEach(function (t) { t.parentNode.removeChild(t); }); // a dica própria substitui a nativa

    function limitar() {
      view.w = Math.min(Math.max(view.w, QUADRO_W / 14), QUADRO_W);
      view.h = view.w * (QUADRO_H / QUADRO_W);
      view.x = Math.min(Math.max(view.x, 0), QUADRO_W - view.w);
      view.y = Math.min(Math.max(view.y, 0), QUADRO_H - view.h);
    }
    function aplicar() {
      limitar();
      svg.setAttribute("viewBox", view.x.toFixed(1) + " " + view.y.toFixed(1) + " " + view.w.toFixed(1) + " " + view.h.toFixed(1));
      var k = view.w / (svg.getBoundingClientRect().width || QUADRO_W);
      svg.style.setProperty("--k", k.toFixed(4));
      quadro.classList.toggle("ms-longe", view.w > QUADRO_W / 2.2);
    }
    function paraSvg(cx, cy) {
      var r = svg.getBoundingClientRect();
      return { x: view.x + (cx - r.left) / r.width * view.w, y: view.y + (cy - r.top) / r.height * view.h };
    }
    function zoom(f, p) {
      p = p || { x: view.x + view.w / 2, y: view.y + view.h / 2 };
      var nw = Math.min(Math.max(view.w * f, QUADRO_W / 14), QUADRO_W), real = nw / view.w;
      view.x = p.x - (p.x - view.x) * real;
      view.y = p.y - (p.y - view.y) * real;
      view.w = nw;
      aplicar();
    }
    function enquadrar(pts, folga) {
      var xs = pts.map(function (p) { return p.x; }), ys = pts.map(function (p) { return p.y; });
      var minx = Math.min.apply(null, xs), maxx = Math.max.apply(null, xs), miny = Math.min.apply(null, ys), maxy = Math.max.apply(null, ys);
      var w = Math.max(maxx - minx, maxy - miny, 90) * (1 + (folga || 0.5));
      view.w = w; view.x = (minx + maxx) / 2 - w / 2; view.y = (miny + maxy) / 2 - w * (QUADRO_H / QUADRO_W) / 2;
      aplicar();
    }
    function ponto(el) { var t = el.getAttribute("transform").match(/translate\(([-\d.]+) ([-\d.]+)\)/); return { x: +t[1], y: +t[2] }; }

    var ptrs = {}, ultimoDist = 0, arrastou = false;
    svg.addEventListener("pointerdown", function (e) {
      ptrs[e.pointerId] = { x: e.clientX, y: e.clientY };
      if (Object.keys(ptrs).length === 1) arrastou = false;
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
    function soltar(e) { delete ptrs[e.pointerId]; ultimoDist = 0; svg.classList.remove("ms-arrastando"); setTimeout(function () { arrastou = false; }, 0); }
    svg.addEventListener("pointerup", soltar);
    svg.addEventListener("pointercancel", soltar);
    svg.addEventListener("wheel", function (e) {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      zoom(e.deltaY > 0 ? 1.2 : 1 / 1.2, paraSvg(e.clientX, e.clientY));
    }, { passive: false });
    svg.addEventListener("dblclick", function (e) { if (e.target.closest(".ms-u")) return; zoom(0.5, paraSvg(e.clientX, e.clientY)); });
    quadro.addEventListener("keydown", function (e) {
      if (e.target !== svg && e.target !== quadro) return;
      var passo = view.w * 0.12;
      var acoes = { ArrowLeft: function () { view.x -= passo; }, ArrowRight: function () { view.x += passo; }, ArrowUp: function () { view.y -= passo; }, ArrowDown: function () { view.y += passo; }, "+": function () { zoom(0.7); }, "=": function () { zoom(0.7); }, "-": function () { zoom(1 / 0.7); } };
      if (acoes[e.key]) { e.preventDefault(); acoes[e.key](); aplicar(); }
    });
    function ligar(c, fn) { var b = q(c); if (b) b.addEventListener("click", fn); }
    ligar(".ms-mais", function () { zoom(0.6); });
    ligar(".ms-menos", function () { zoom(1 / 0.6); });
    ligar(".ms-tudo", function () { view = { x: vistaInicial.x, y: vistaInicial.y, w: vistaInicial.w, h: vistaInicial.h }; aplicar(); });
    window.addEventListener("resize", aplicar);

    function fmtKm(m) { return m < 1000 ? Math.round(m / 10) * 10 + " m" : (m / 1000).toFixed(1).replace(".", ",") + " km"; }
    function nomeGrupo(u) { return NOMES[u.dataset.grupo] || ""; }
    function dist(u) { return distancias.has(u) ? " · a " + fmtKm(distancias.get(u)) + " de você" : ""; }
    function mostrarDica(el) {
      if (!dica) return;
      dica.textContent = "";
      var b = document.createElement("strong"); b.textContent = el.dataset.nome || el.dataset.dica; dica.appendChild(b);
      if (el.dataset.nome) { var s = document.createElement("span"); s.textContent = nomeGrupo(el) + dist(el); dica.appendChild(s); }
      else if (el.dataset.dica2) { var s2 = document.createElement("span"); s2.textContent = el.dataset.dica2; dica.appendChild(s2); }
      dica.hidden = false;
      var r = el.getBoundingClientRect(), qd = quadro.getBoundingClientRect();
      var x = r.left - qd.left + r.width / 2, y = r.top - qd.top;
      var meia = dica.offsetWidth / 2;
      dica.style.left = Math.min(Math.max(x, meia + 4), qd.width - meia - 4) + "px";
      dica.style.top = Math.min(Math.max(y < 70 ? y + r.height + 8 : y - 8, 4), qd.height - 4) + "px";
      dica.classList.toggle("abaixo", y < 70);
    }
    function esconderDica() { if (dica) dica.hidden = true; }
    function linha(rotulo, valor) { var d = document.createElement("div"), t = document.createElement("dt"), v = document.createElement("dd"); t.textContent = rotulo; v.textContent = valor; d.appendChild(t); d.appendChild(v); return d; }
    function selecionar(u) {
      unidades.forEach(function (x) { x.classList.toggle("ms-sel", x === u); });
      var tinhaFoco = document.activeElement === u;
      u.parentNode.appendChild(u);
      if (tinhaFoco) u.focus({ preventScroll: true });
      atual = u;
      if (!painelSel) return;
      painelSel.textContent = "";
      var h = document.createElement("h3"); h.textContent = u.dataset.nome; painelSel.appendChild(h);
      var dl = document.createElement("dl"); dl.className = "ms-dl";
      var tipo = nomeGrupo(u); if (tipo) dl.appendChild(linha("Tipo", tipo));
      var detalhes = []; try { detalhes = JSON.parse(u.dataset.detalhes || "[]"); } catch (e) { detalhes = []; }
      detalhes.forEach(function (p) { if (p[1]) dl.appendChild(linha(String(p[0]), String(p[1]))); });
      if (distancias.has(u)) dl.appendChild(linha("Distância em linha reta", fmtKm(distancias.get(u))));
      painelSel.appendChild(dl);
      if (u.dataset.url && /^[\w./-]+$/.test(u.dataset.url)) {
        var a0 = document.createElement("a"); a0.className = "ms-link"; a0.href = u.dataset.url; a0.textContent = u.dataset.urlRotulo || "Ver detalhes";
        painelSel.appendChild(a0); painelSel.appendChild(document.createElement("br"));
      }
      if (u.dataset.lat && u.dataset.lon) {
        var a = document.createElement("a");
        a.rel = "noopener noreferrer"; a.className = "ms-link";
        var la = u.dataset.lat, lo = u.dataset.lon;
        a.href = "https://www.openstreetmap.org/?mlat=" + la + "&mlon=" + lo + "#map=17/" + la + "/" + lo;
        a.textContent = "Ver no OpenStreetMap";
        painelSel.appendChild(a);
        if (posicao) {
          var b = document.createElement("a");
          b.rel = "noopener noreferrer"; b.className = "ms-link";
          b.href = "https://www.openstreetmap.org/directions?from=" + posicao.lat.toFixed(3) + "," + posicao.lon.toFixed(3) + "&to=" + la + "," + lo;
          b.textContent = "Como chegar (envia ao OpenStreetMap a sua posição aproximada, a cerca de 100 m)";
          painelSel.appendChild(document.createElement("br"));
          painelSel.appendChild(b);
        }
      }
    }
    unidades.forEach(function (u) {
      u.addEventListener("mouseenter", function () { if (!arrastou) mostrarDica(u); });
      u.addEventListener("mouseleave", esconderDica);
      u.addEventListener("focus", function () {
        var p = ponto(u);
        if (p.x < view.x || p.x > view.x + view.w || p.y < view.y || p.y > view.y + view.h) { view.x = p.x - view.w / 2; view.y = p.y - view.h / 2; aplicar(); }
        mostrarDica(u);
      });
      u.addEventListener("blur", esconderDica);
      u.addEventListener("click", function (e) { e.stopPropagation(); if (!arrastou) selecionar(u); });
      u.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selecionar(u); } });
    });
    celulas.forEach(function (c) {
      c.addEventListener("mouseenter", function () { if (!arrastou) mostrarDica(c); });
      c.addEventListener("mouseleave", esconderDica);
      c.addEventListener("click", function (e) { e.stopPropagation(); if (!arrastou) mostrarDica(c); });
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") esconderDica(); });
    svg.addEventListener("click", esconderDica);

    // filtros: cada grupo de caixas (data-filtro) tem a sua regra; a unidade aparece se passar em todos
    var filtros = Array.prototype.slice.call(raiz.querySelectorAll(".ms-filtro input"));
    function passa(el) {
      var porFiltro = {};
      filtros.forEach(function (c) {
        var tipo = c.dataset.filtro || "grupo";
        var lista = porFiltro[tipo] = porFiltro[tipo] || { marcadas: [], total: 0 };
        lista.total++;
        if (c.checked) lista.marcadas.push(c.value);
      });
      return Object.keys(porFiltro).every(function (tipo) {
        var f = porFiltro[tipo];
        if (f.marcadas.length === f.total) return true;
        var valores = (el.dataset[tipo === "grupo" ? "grupo" : tipo] || "").split(" ");
        return f.marcadas.some(function (m) { return valores.indexOf(m) !== -1; });
      });
    }
    function refiltrar() {
      unidades.forEach(function (u) { u.classList.toggle("ms-off", !passa(u)); });
      celulas.forEach(function (c) { c.classList.toggle("ms-off", !passa(c)); });
      if (posicao) listarProximas(false);
    }
    filtros.forEach(function (c) { c.addEventListener("change", refiltrar); });
    function visivel(u) { return !u.classList.contains("ms-off"); }

    // localização, sempre calculada no navegador
    function metros(la1, lo1, la2, lo2) {
      var R = 6371000, r = Math.PI / 180, dla = (la2 - la1) * r, dlo = (lo2 - lo1) * r;
      var a = Math.sin(dla / 2) * Math.sin(dla / 2) + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dlo / 2) * Math.sin(dlo / 2);
      return 2 * R * Math.asin(Math.sqrt(a));
    }
    function xy(lat, lon) { return { x: lon * afim.k * afim.escala + afim.dx, y: -lat * afim.escala + afim.dy }; }
    function elem(nome, attrs) { var e = document.createElementNS(NS, nome); Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); }); return e; }
    function aviso(t) { if (msg) msg.textContent = t; }
    var contorno = (svg.dataset.contorno || "").split(";").filter(Boolean).map(function (p) { var v = p.split(",").map(Number); return { la: v[0], lo: v[1] }; });
    function dentroDoMunicipio(lat, lon) {
      var ok = false;
      for (var i = 0, j = contorno.length - 1; i < contorno.length; j = i++) {
        var a = contorno[i], b = contorno[j];
        if ((a.la > lat) !== (b.la > lat) && lon < (b.lo - a.lo) * (lat - a.la) / (b.la - a.la) + a.lo) ok = !ok;
      }
      return ok;
    }
    function marcar(lat, lon, rotulo) {
      if (!dentroDoMunicipio(lat, lon)) {
        posicao = null; distancias.clear(); gAneis.textContent = ""; gVoce.setAttribute("hidden", ""); if (painelProx) painelProx.hidden = true;
        aviso("Esse ponto fica fora de Sorocaba, então não mostro distâncias. Escolha um bairro da cidade.");
        return;
      }
      posicao = { lat: lat, lon: lon };
      var p = xy(lat, lon), upm = afim.escala / 111320;
      gAneis.textContent = ""; gVoce.textContent = "";
      [1000, 2000, 5000].forEach(function (m) {
        gAneis.appendChild(elem("circle", { cx: p.x, cy: p.y, r: m * upm, class: "ms-anel" }));
        var t = elem("text", { x: p.x, y: p.y - m * upm, class: "ms-anel-t", "text-anchor": "middle", dy: "-0.35em" }); t.textContent = m / 1000 + " km"; gAneis.appendChild(t);
      });
      var g = elem("g", { transform: "translate(" + p.x.toFixed(1) + " " + p.y.toFixed(1) + ")" });
      g.appendChild(elem("circle", { r: 15, class: "ms-voce-halo" }));
      g.appendChild(elem("circle", { r: 7, class: "ms-voce-ponto" }));
      gVoce.appendChild(g);
      gVoce.removeAttribute("hidden");
      distancias.clear();
      unidades.forEach(function (u) { if (u.dataset.lat) distancias.set(u, Math.round(metros(lat, lon, +u.dataset.lat, +u.dataset.lon))); });
      aviso("Posição marcada: " + rotulo + ". Ela fica só no seu navegador; só vai ao OpenStreetMap se você abrir “Como chegar”.");
      listarProximas();
      if (atual) selecionar(atual);
    }
    function listarProximas(reenquadrar) {
      if (!painelProx) return;
      painelProx.textContent = "";
      var titulo = document.createElement("h3"); titulo.textContent = "Mais perto de você"; painelProx.appendChild(titulo);
      var ul = document.createElement("ul"); ul.className = "ms-prox";
      var achou = [];
      ORDEM.forEach(function (g) {
        var lista = unidades.filter(function (u) { return u.dataset.grupo === g && visivel(u) && distancias.has(u); }).sort(function (a, b) { return distancias.get(a) - distancias.get(b); });
        if (!lista.length) return;
        var u = lista[0];
        achou.push(ponto(u));
        var li = document.createElement("li"), b = document.createElement("button");
        b.type = "button"; b.className = "ms-prox-b";
        var tipo = document.createElement("span"); tipo.className = "ms-prox-t"; tipo.textContent = NOMES[g] || g;
        var nome = document.createElement("strong"); nome.textContent = u.dataset.nome;
        var d = document.createElement("span"); d.className = "ms-prox-d"; d.textContent = fmtKm(distancias.get(u)) + " em linha reta" + (u.dataset.resumo ? " · " + u.dataset.resumo : "");
        b.appendChild(tipo); b.appendChild(nome); b.appendChild(d);
        b.addEventListener("click", function () { selecionar(u); enquadrar([ponto(u), xy(posicao.lat, posicao.lon)], 0.6); });
        li.appendChild(b); ul.appendChild(li);
      });
      painelProx.appendChild(ul);
      if (NOTA) { var nota = document.createElement("p"); nota.className = "pequeno suave"; nota.textContent = NOTA; painelProx.appendChild(nota); }
      painelProx.hidden = false;
      if (reenquadrar !== false && achou.length) enquadrar(achou.concat([xy(posicao.lat, posicao.lon)]), 0.35);
    }
    var btnGps = q(".ms-gps");
    if (btnGps) btnGps.addEventListener("click", function () {
      if (!navigator.geolocation) { aviso("Seu navegador não informa a localização. Escolha o bairro."); return; }
      aviso("Procurando sua posição…");
      btnGps.disabled = true;
      navigator.geolocation.getCurrentPosition(function (p) {
        btnGps.disabled = false;
        if (p.coords.accuracy > 3000) { aviso("O navegador só soube sua posição com erro de vários quilômetros. Escolha o bairro para ver as unidades mais perto."); return; }
        marcar(p.coords.latitude, p.coords.longitude, "sua localização" + (p.coords.accuracy > 1000 ? " (aproximada)" : ""));
      }, function (err) {
        btnGps.disabled = false;
        aviso(err.code === 1 ? "A localização foi negada. Escolha o bairro ao lado." : "Não consegui sua posição. Escolha o bairro ao lado.");
      }, { enableHighAccuracy: false, timeout: 12000, maximumAge: 60000 });
    });

    var campo = q(".ms-bairro"), lista = q(".ms-bairros"), form = q(".ms-bairro-form"), bairros = null, carregando = null;
    function norm(s) { return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").trim(); }
    function carregar() {
      if (carregando) return carregando;
      carregando = fetch(svg.dataset.bairros).then(function (r) { if (!r.ok) throw new Error("http"); return r.json(); }).then(function (d) {
        bairros = d.bairros;
        var visto = {};
        bairros.forEach(function (b) { if (visto[b.n]) return; visto[b.n] = 1; var o = document.createElement("option"); o.value = b.n; lista.appendChild(o); });
      }).catch(function () { aviso("Não consegui carregar a lista de bairros."); });
      return carregando;
    }
    if (campo && form) {
      campo.addEventListener("focus", carregar);
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        carregar().then(function () {
          var qb = norm(campo.value);
          if (!bairros || qb.length < 3) { aviso("Digite o nome do bairro e escolha um da lista."); return; }
          var iguais = bairros.filter(function (x) { return norm(x.n) === qb; });
          var achados = iguais.length ? iguais : bairros.filter(function (x) { return norm(x.n).indexOf(qb) !== -1; });
          var nomes = {};
          achados.forEach(function (x) { nomes[x.n] = 1; });
          if (!achados.length) { aviso("Não achei esse bairro. Escolha um da lista."); return; }
          if (Object.keys(nomes).length > 1) { aviso("Vários bairros combinam com “" + campo.value + "”. Digite mais letras e escolha da lista."); return; }
          var b = achados[0];
          marcar(b.la, b.lo, "centro do bairro " + b.n + (achados.length > 1 ? " (há mais de um com esse nome; usei o primeiro)" : "") + ", aproximado");
        });
      });
    }
    aplicar();
  }
})();
