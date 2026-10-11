"""Sinistros de trânsito de Sorocaba (Infosiga SP, Detran-SP) agregados por mês, hora, tipo, via e célula do mapa.

Os CSVs do estado têm um sinistro por linha, com logradouro, hora e coordenada exatas. Só contagens
agregadas são gravadas; nenhum ponto individual (em especial de sinistro fatal) chega ao repositório.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import shutil
import time
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from scripts.geo import carregar_contorno, dentro  # noqa: F401  (reexportados para os testes)
from scripts.infosiga_regras import CELULA_MINIMA, DETALHE_MINIMO, VIA_MINIMA

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "infosiga"
CKAN = "https://dadosabertos.sp.gov.br/api/3/action/package_show?id=eventos-de-sinistro"
HOSTS = {"dadosabertos.sp.gov.br", "infosiga.detran.sp.gov.br"}
IBGE = "3552205"
ANOS_ATRAS = 4
ANOS_RECALCULADOS = 2  # linhas já publicadas podem ser revisadas: o ano corrente e o anterior são sempre refeitos
LIMITE_ARQUIVO = 30 * 1024 * 1024
CELULA = 0.005
PLUS_CODE = re.compile(r"\b[23456789CFGHJMPQRVWX]{2,8}\+[23456789CFGHJMPQRVWX]{0,3}(?!\w)")
COORD_TEXTO = re.compile(r"-?\d{1,3}[.,]\d{4,}")  # 4+ casas: coordenada; "KM 101,500" e "RUA 1.000" passam
DIAS = {"Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"}
TABELAS = {
    "mensal": ["ano", "mes", "tipo_registro", "sinistros", "vitimas_fatais", "vitimas_graves"],
    "hora": ["ano", "dia_semana", "hora", "n"],
    "tipo": ["ano", "tipo", "n"],
    "via": ["ano", "logradouro", "n"],
    "grade": ["ano", "lat", "lon", "n"],
}


def url_segura(url: object) -> str:
    """Sem query nem fragmento: a URL do CKAN pode carregar assinatura e o log do Actions é público."""
    u = urlsplit(str(url))
    return f"{u.scheme}://{u.hostname}{f':{u.port}' if u.port else ''}{u.path}"


class ErroHTTP(RuntimeError):
    def __init__(self, status: int, onde: str):
        super().__init__(f"HTTP {status} em {onde}")
        self.status = status


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host not in HOSTS:
        raise ValueError(f"requisição fora dos hosts esperados: {url_segura(r.url)}")


def com_tentativas(fn):
    for n in range(4):
        try:
            return fn()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            definitivo = n == 3 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500 and e.response.status_code != 429) or isinstance(e, httpx.TooManyRedirects)
            if definitivo:
                req = getattr(e, "_request", None) or (e.request if isinstance(e, httpx.HTTPStatusError) else None)
                onde = url_segura(req.url) if req else "?"
                if isinstance(e, httpx.HTTPStatusError):
                    raise ErroHTTP(e.response.status_code, onde) from None
                raise RuntimeError(f"falha de rede ({type(e).__name__}) em {onde}") from None
            time.sleep(2**n * 2)


def baixar(c: httpx.Client, url: str) -> bytes:
    def uma() -> bytes:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            corpo = bytearray()
            for pedaco in r.iter_bytes(1 << 20):
                corpo += pedaco
                if len(corpo) > LIMITE_ARQUIVO:
                    raise ValueError("arquivo acima do limite esperado")
        return bytes(corpo)
    return com_tentativas(uma)


def numero(v: str) -> float | None:
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def inteiro(v: str | None, invalidos: Counter) -> int:
    if not v or not v.strip():
        return 0
    n = numero(v)
    if n is None or n < 0:
        invalidos["contagem"] += 1
        return 0
    return int(n)


def logradouro(v: str | None) -> str | None:
    via = " ".join((v or "").split()).upper()
    if not via or PLUS_CODE.search(via) or COORD_TEXTO.search(via):  # Plus Code ou coordenada no lugar do nome localiza o ponto quase exatamente
        return None
    return texto_seguro(via)


def texto_seguro(v: str) -> str:
    """Evita que o CSV seja lido como fórmula em planilhas."""
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def agregar_mes(texto: str, ano: int, mes: int, cont: dict[str, Counter], contorno: list[tuple[float, float]] | None = None, invalidos: Counter | None = None, com_coord: Counter | None = None) -> int:
    contorno = contorno if contorno is not None else carregar_contorno()
    invalidos = invalidos if invalidos is not None else Counter()
    com_coord = com_coord if com_coord is not None else Counter()
    n = 0
    for r in csv.DictReader(io.StringIO(texto), delimiter=";"):
        if r.get("cod_ibge") != IBGE:
            continue
        n += 1
        tipo = r["tipo_registro"].strip()
        k = (ano, mes, tipo)
        cont["mensal"][k + ("sinistros",)] += 1
        cont["mensal"][k + ("vitimas_fatais",)] += inteiro(r.get("qtd_gravidade_fatal"), invalidos)
        cont["mensal"][k + ("vitimas_graves",)] += inteiro(r.get("qtd_gravidade_grave"), invalidos)
        if tipo == "NOTIFICACAO":  # registro incompleto: fica só na contagem mensal
            continue
        hora = r.get("hora_sinistro", "")[:2]
        dia = r.get("dia_da_semana", "").strip()
        if dia not in DIAS:
            invalidos["dia_semana"] += 1
        elif re.fullmatch(r"\d\d", hora):
            cont["hora"][(ano, dia, hora)] += 1
        cont["tipo"][(ano, texto_seguro((r.get("tp_sinistro_primario") or "NÃO INFORMADO").strip()))] += 1
        via = logradouro(r.get("logradouro"))
        if via:
            cont["via"][(ano, via)] += 1
        la, lo = numero(r.get("latitude", "")), numero(r.get("longitude", ""))
        if la is not None and lo is not None and dentro(contorno, la, lo):
            com_coord["n"] += 1
            cont["grade"][(ano, round((math.floor(la / CELULA) + 0.5) * CELULA, 4), round((math.floor(lo / CELULA) + 0.5) * CELULA, 4))] += 1
    return n


def csv_texto(campos: list[str], cont: Counter, mensal: bool = False) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(campos)
    if mensal:
        chaves = sorted({k[:3] for k in cont})
        for a, m, t in chaves:
            w.writerow([a, m, t, cont[(a, m, t, "sinistros")], cont[(a, m, t, "vitimas_fatais")], cont[(a, m, t, "vitimas_graves")]])
    else:
        for k in sorted(cont):
            w.writerow([*k, cont[k]])
    return buf.getvalue()


def suprimir(cont: dict[str, Counter]) -> int:
    """Remove do raw células do mapa, vias e combinações de hora/tipo raras; devolve quantas células do mapa foram descartadas."""
    descartadas = 0
    for t, minimo in (("grade", CELULA_MINIMA), ("via", VIA_MINIMA), ("hora", DETALHE_MINIMO), ("tipo", DETALHE_MINIMO)):
        for k in [k for k, n in cont[t].items() if n < minimo]:
            del cont[t][k]
            descartadas += 1 if t == "grade" else 0
    return descartadas


def catalogo(c: httpx.Client) -> dict[tuple[int, int], dict]:
    por_mes: dict[tuple[int, int], dict] = {}
    for r in json.loads(baixar(c, CKAN))["result"]["resources"]:
        m = re.search(r"sinistros_(\d\d)-(\d{4})\.csv", r.get("url", ""))
        if m:
            chave = (int(m.group(2)), int(m.group(1)))
            if not 1 <= chave[1] <= 12:
                raise ValueError(f"mês inválido no catálogo: {url_segura(r['url']).rsplit('/', 1)[-1]}")
            if chave in por_mes:
                raise ValueError(f"recurso duplicado no catálogo: {chave[1]:02d}/{chave[0]}")
            por_mes[chave] = r
    if not por_mes:
        raise ValueError("nenhum arquivo mensal de sinistros no catálogo")
    return por_mes


def coletar(acesso_em: date, destino: Path = DESTINO, transporte: httpx.BaseTransport | None = None) -> list[int]:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / "manifesto.json"
    man = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"anos": {}}
    feitos = []
    pendentes: list[tuple[Path, dict[str, str]]] = []  # só grava depois que todos os anos foram baixados e validados
    contorno = carregar_contorno()
    with httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=True, max_redirects=3, headers={"User-Agent": "Mozilla/5.0 SorocabaEmDados/1.0"}, event_hooks={"request": [so_host_confiavel]}, transport=transporte) as c:
        por_mes = {k: v for k, v in catalogo(c).items() if k <= (acesso_em.year, acesso_em.month)}  # mês futuro no catálogo é erro da fonte
        primeiro = acesso_em.year - ANOS_ATRAS
        for ano in range(primeiro, acesso_em.year + 1):
            pasta = destino / str(ano)
            if ano < acesso_em.year - ANOS_RECALCULADOS + 1 and (pasta / "mensal.csv").exists():
                continue
            meses = sorted(m for (a, m) in por_mes if a == ano)
            if not meses:
                continue
            anteriores = man["anos"].get(str(ano), {}).get("meses", [])
            if set(anteriores) - set(meses):
                raise ValueError(f"{ano}: catálogo perdeu os meses {sorted(set(anteriores) - set(meses))} que o manifesto já tinha; coleta abortada")
            cont = {t: Counter() for t in TABELAS}
            invalidos: Counter = Counter()
            com_coord: Counter = Counter()
            origem = {}
            total = 0
            for mes in meses:
                url = por_mes[(ano, mes)]["url"]
                try:
                    bruto = baixar(c, url)
                except ErroHTTP as e:
                    if e.status != 403:
                        raise
                    por_mes = catalogo(c)  # URL possivelmente assinada expirou: relê o catálogo uma vez
                    if (ano, mes) not in por_mes:
                        raise ValueError(f"{mes:02d}/{ano} sumiu do catálogo após o 403") from None
                    url = por_mes[(ano, mes)]["url"]
                    bruto = baixar(c, url)
                origem[f"{mes:02d}"] = {"url": url_segura(url), "bytes": len(bruto), "sha256": hashlib.sha256(bruto).hexdigest(), "last_modified": por_mes[(ano, mes)].get("last_modified") or por_mes[(ano, mes)].get("metadata_modified")}
                total += agregar_mes(bruto.decode("latin-1"), ano, mes, cont, contorno, invalidos, com_coord)
            if not total:
                raise ValueError(f"nenhum sinistro de Sorocaba em {ano}")
            celulas_descartadas = suprimir(cont)
            textos = {t: csv_texto(campos, cont[t], mensal=(t == "mensal")) for t, campos in TABELAS.items()}
            hashes = {t: hashlib.sha256(x.encode("utf-8")).hexdigest() for t, x in textos.items()}
            pendentes.append((pasta, textos))
            man["anos"][str(ano)] = {
                "meses": meses, "registros": total, "sha256_csv": hashes, "coletado_em": acesso_em.isoformat(),
                "com_coordenada": com_coord["n"], "celulas_descartadas": celulas_descartadas,
                "valores_invalidos": dict(invalidos), "origem": origem,
            }
            feitos.append(ano)
    for pasta, textos in pendentes:
        pasta.mkdir(exist_ok=True)
        for t, texto in textos.items():
            (pasta / f"{t}.csv").write_text(texto, encoding="utf-8")
    for a in [a for a in man["anos"] if not a.isdigit() or int(a) < primeiro]:  # fora da janela: o build e o mapa não crescem sem limite
        if not re.fullmatch(r"[0-9]{4}", a):
            raise ValueError(f"ano inválido no manifesto: {a!r}")
        del man["anos"][a]
        shutil.rmtree(destino / a, ignore_errors=True)
        man.setdefault("anos_removidos", {})[a] = acesso_em.isoformat()
    man["fonte"] = "Infosiga SP (Detran-SP), eventos de sinistro, CC BY 4.0, via dadosabertos.sp.gov.br"
    man["verificado_em"] = acesso_em.isoformat()
    arq.write_text(json.dumps(man, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return feitos


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("atualizados:", coletar(args.acesso_em) or "nenhum")


if __name__ == "__main__":
    main()
