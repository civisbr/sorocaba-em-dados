"""Ocorrências nas rodovias de Sorocaba (ARTESP, Centro de Controle Multimodal) agregadas por mês, rodovia, tipo e trecho de 5 km.

A API devolve uma ocorrência por registro, com relato livre, veículos e ponto exato. Só contagens agregadas
são gravadas; nenhum texto livre, ponto ou data/hora individual chega ao repositório. A chave vem de
ARTESP_API_KEY (segredo do repositório) e nunca é registrada nem aparece em mensagem de erro.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "artesp"
HOST = "ccm.artesp.sp.gov.br"
URL = f"https://{HOST}/rodovias/api/ocorrencias/"
IBGE = "3552205"
PRIMEIRO_DIA = date(2021, 11, 16)  # início da série na API
ANOS_RECALCULADOS = 2  # a fonte corrige registros depois de publicá-los: o ano corrente e o anterior são sempre refeitos
POR_PAGINA = 100
MAX_PAGINAS = 10
LIMITE_RESPOSTA = 5 * 1024 * 1024
TIPOS = {"Colisão", "Choque", "Atropelamento", "Engavetamento", "Tombamento", "Capotamento", "Queda", "Incêndio"}  # texto fora da lista vira "Outros"
TRECHO_KM = 5
TRECHO_MINIMO = 3  # acidentes por trecho, por ano
DETALHE_MINIMO = 3  # rodovia e tipo de acidente, por ano
CLASSES = {"Acidente", "Evento natural", "Obra", "Ocorrência"}
SEM_FERIMENTO = {"ILESA", "EVADIU-SE"}
VITIMAS = {"FATAL": "fatais", "GRAVE": "feridos", "MODERADA": "feridos", "LEVE": "feridos"}
NOME_RODOVIA = re.compile(r"[A-Z]{2,4} ?\d{1,3}(?:/\d{1,3})?(?: [A-Z])?")
TABELAS = {
    "mensal": ["ano", "mes", "classe", "ocorrencias", "vitimas_fatais", "feridos"],
    "rodovia": ["ano", "rodovia", "acidentes"],
    "tipo": ["ano", "tipo", "acidentes"],
    "trecho": ["ano", "rodovia", "km_ini", "acidentes"],
}


class ErroHTTP(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status} na API da ARTESP")
        self.status = status


class LimiteExcedido(RuntimeError):
    pass


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host != HOST:
        raise ValueError(f"requisição fora do host esperado: {r.url.host}")


def texto_seguro(v: str) -> str:
    """Evita que o CSV seja lido como fórmula em planilhas."""
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def rodovia_nome(v: object) -> str | None:
    nome = " ".join(str(v or "").replace("-", " ").split()).upper()
    return nome if NOME_RODOVIA.fullmatch(nome) else None


def pagina(c: httpx.Client, params: dict[str, str]) -> dict:
    """Uma chamada, sem retentativa em 429 (a cota é de 12 por hora) nem em erro de cliente."""
    for n in range(3):
        try:
            r = c.get(URL, params=params)
        except httpx.RequestError as e:
            if n == 2:
                raise RuntimeError(f"falha de rede ({type(e).__name__}) na API da ARTESP") from None
            time.sleep(2 ** n * 2)
            continue
        if r.status_code == 429:
            raise LimiteExcedido("cota horária da API da ARTESP esgotada; tente de novo depois")
        if r.status_code >= 500 and n < 2:
            time.sleep(2 ** n * 2)
            continue
        if r.status_code != 200:
            raise ErroHTTP(r.status_code)
        if len(r.content) > LIMITE_RESPOSTA:
            raise ValueError("resposta da ARTESP acima do limite esperado")
        try:
            d = r.json()
        except ValueError:
            raise RuntimeError("resposta da ARTESP não é JSON") from None
        if not isinstance(d, dict):
            raise ValueError("resposta da ARTESP sem o formato esperado")
        return d
    raise RuntimeError("falha na API da ARTESP")


def ocorrencias(c: httpx.Client, ini: date, fim: date) -> tuple[list[dict], int]:
    base = {"filtro_municipio": IBGE, "filtro_data_inicio": ini.isoformat(), "filtro_data_fim": fim.isoformat(), "include": "fim", "limit": str(POR_PAGINA)}
    achados: dict[str, dict] = {}
    total = None
    for i in range(MAX_PAGINAS):
        d = pagina(c, {**base, "offset": str(i * POR_PAGINA)})
        meta, itens = d.get("meta"), d.get("results")
        if not isinstance(meta, dict) or not isinstance(itens, list) or len(itens) > POR_PAGINA or not isinstance(meta.get("count"), int):
            raise ValueError("resposta da ARTESP sem meta/results esperados")
        total = meta["count"]
        for o in itens:
            if isinstance(o, dict) and isinstance(o.get("slug"), str):
                achados[o["slug"]] = o
        if not meta.get("next") or len(achados) >= total:
            break
    else:
        raise ValueError(f"mais de {MAX_PAGINAS} páginas na janela {ini}..{fim}")
    if total is None or len(achados) != total:
        raise ValueError(f"{ini}..{fim}: a API anunciou {total} ocorrências e a coleta tem {len(achados)}")
    return list(achados.values()), total


def data_da(o: dict) -> datetime | None:
    for campo in ("dt_hr_oc", "dt_hr_conhecimento"):
        v = o.get(campo)
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                continue
    return None


def agregar(itens: list[dict], cont: dict[str, Counter], invalidos: Counter, ano: int | None = None) -> int:
    n = 0
    for o in itens:
        if not any(isinstance(m, dict) and m.get("cod_ibge") == IBGE for m in o.get("municipios") or []):
            invalidos["fora_do_municipio"] += 1
            continue
        d, classe = data_da(o), o.get("classe")
        if d is None or classe not in CLASSES:
            invalidos["data_ou_classe"] += 1
            continue
        if ano is not None and d.year != ano:  # evita contar duas vezes um evento que a busca devolve em duas janelas
            invalidos["fora_da_janela"] += 1
            continue
        n += 1
        k = (d.year, d.month, classe)
        cont["mensal"][k + ("ocorrencias",)] += 1
        if classe != "Acidente":
            continue
        for v in o.get("fim") or []:
            qtd = v.get("qtd") if isinstance(v, dict) else None
            grupo = VITIMAS.get(v.get("tipo")) if isinstance(v, dict) else None
            if isinstance(v, dict) and v.get("tipo") not in VITIMAS and v.get("tipo") not in SEM_FERIMENTO:
                invalidos["vitima_tipo_desconhecido"] += 1
            if grupo and isinstance(qtd, int) and 0 < qtd < 1000:
                cont["mensal"][k + ({"fatais": "vitimas_fatais", "feridos": "feridos"}[grupo],)] += qtd
        via = rodovia_nome(o.get("rodovia", {}).get("nome") if isinstance(o.get("rodovia"), dict) else None)
        if not via:
            invalidos["rodovia_fora_do_padrao"] += 1
        if via:
            cont["rodovia"][(d.year, via)] += 1
        tipo = " ".join(str(o.get("subclasse_ac") or "").split())
        if tipo:
            cont["tipo"][(d.year, tipo if tipo in TIPOS else "Outros")] += 1
        km = o.get("km_inicial")
        if via and isinstance(km, (int, float)) and 0 <= km < 1000:
            cont["trecho"][(d.year, via, int(km // TRECHO_KM) * TRECHO_KM)] += 1
    return n


def suprimir(cont: dict[str, Counter]) -> None:
    for t, minimo in (("rodovia", DETALHE_MINIMO), ("tipo", DETALHE_MINIMO), ("trecho", TRECHO_MINIMO)):
        for k in [k for k, n in cont[t].items() if n < minimo]:
            del cont[t][k]


def csv_texto(campos: list[str], cont: Counter, mensal: bool = False) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(campos)
    if mensal:
        for a, m, cl in sorted({k[:3] for k in cont}):
            w.writerow([a, m, cl, cont[(a, m, cl, "ocorrencias")], cont[(a, m, cl, "vitimas_fatais")], cont[(a, m, cl, "feridos")]])
    else:
        for k in sorted(cont):
            w.writerow([*k, cont[k]])
    return buf.getvalue()


def janelas(acesso_em: date) -> list[tuple[int, date, date]]:
    return [(a, max(date(a, 1, 1), PRIMEIRO_DIA), min(date(a, 12, 31), acesso_em)) for a in range(PRIMEIRO_DIA.year, acesso_em.year + 1)]


def coletar(chave: str, acesso_em: date, destino: Path = DESTINO, transporte: httpx.BaseTransport | None = None) -> list[int]:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    if not re.fullmatch(r"[A-Za-z0-9_]{20,200}", chave):
        raise ValueError("ARTESP_API_KEY ausente ou em formato inesperado")
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / "manifesto.json"
    man = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"anos": {}}
    feitos, pendentes = [], []
    cabecalhos = {"Authorization": f"Api-Key {chave}", "User-Agent": "SorocabaEmDados/1.0 (+https://civisbr.github.io/sorocaba-em-dados/)"}
    with httpx.Client(timeout=httpx.Timeout(30, read=60), follow_redirects=False, headers=cabecalhos, event_hooks={"request": [so_host_confiavel]}, transport=transporte) as c:
        for ano, ini, fim in janelas(acesso_em):
            pasta = destino / str(ano)
            if ano < acesso_em.year - ANOS_RECALCULADOS + 1 and (pasta / "mensal.csv").exists():
                continue
            itens, total = ocorrencias(c, ini, fim)
            cont = {t: Counter() for t in TABELAS}
            invalidos: Counter = Counter()
            n = agregar(itens, cont, invalidos, ano)
            suprimir(cont)
            if ano == acesso_em.year:  # o ano aberto é regravado todo mês: sem rodovia, tipo e trecho, a diferença entre commits não isola acidentes
                for t in ('rodovia', 'tipo', 'trecho'):
                    cont[t].clear()
            textos = {t: csv_texto(TABELAS[t], cont[t], mensal=t == "mensal") for t in TABELAS}
            h = hashlib.sha256("".join(textos[t] for t in sorted(textos)).encode()).hexdigest()
            meses = sorted({m for (a, m, _cl, _c) in cont["mensal"] if a == ano})
            pendentes.append((pasta, textos, ano, {"janela": [ini.isoformat(), fim.isoformat()], "anunciadas": total, "agregadas": n, "descartadas": dict(invalidos), "meses": meses, "sha256": h}))
            feitos.append(ano)
    for pasta, textos, ano, info in pendentes:  # só grava depois que todas as janelas foram baixadas e validadas
        pasta.mkdir(parents=True, exist_ok=True)
        for t, texto in textos.items():
            (pasta / f"{t}.csv").write_text(texto, encoding="utf-8", newline="")
        man["anos"][str(ano)] = info
    man["verificado_em"] = acesso_em.isoformat()
    arq.write_text(json.dumps(man, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return feitos


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", type=date.fromisoformat, required=True)
    p.add_argument("--destino", type=Path, default=DESTINO)
    args = p.parse_args()
    chave = os.environ.get("ARTESP_API_KEY", "")
    try:
        feitos = coletar(chave, args.acesso_em, args.destino)
    except (LimiteExcedido, ErroHTTP, RuntimeError, ValueError) as e:
        raise SystemExit(f"coleta da ARTESP falhou: {e}") from None
    print(f"anos coletados: {feitos}")


if __name__ == "__main__":
    main()
