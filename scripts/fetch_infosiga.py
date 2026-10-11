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
import time
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "infosiga"
CKAN = "https://dadosabertos.sp.gov.br/api/3/action/package_show?id=eventos-de-sinistro"
HOSTS = {"dadosabertos.sp.gov.br", "infosiga.detran.sp.gov.br"}
IBGE = "3552205"
ANOS_ATRAS = 4
ANOS_RECALCULADOS = 2  # linhas já publicadas podem ser revisadas: o ano corrente e o anterior são sempre refeitos
LIMITE_ARQUIVO = 30 * 1024 * 1024
CELULA = 0.005
TABELAS = {
    "mensal": ["ano", "mes", "tipo_registro", "sinistros", "vitimas_fatais", "vitimas_graves"],
    "hora": ["ano", "dia_semana", "hora", "n"],
    "tipo": ["ano", "tipo", "n"],
    "via": ["ano", "logradouro", "n"],
    "grade": ["ano", "lat", "lon", "n"],
}


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host not in HOSTS:
        raise ValueError(f"requisição fora dos hosts esperados: {r.url}")


def com_tentativas(fn):
    for n in range(4):
        try:
            return fn()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if n == 3 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500):
                raise
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


def agregar_mes(texto: str, ano: int, mes: int, cont: dict[str, Counter]) -> int:
    n = 0
    for r in csv.DictReader(io.StringIO(texto), delimiter=";"):
        if r.get("cod_ibge") != IBGE:
            continue
        n += 1
        tipo = r["tipo_registro"].strip()
        k = (ano, mes, tipo)
        cont["mensal"][k + ("sinistros",)] += 1
        cont["mensal"][k + ("vitimas_fatais",)] += int(float(r.get("qtd_gravidade_fatal") or 0))
        cont["mensal"][k + ("vitimas_graves",)] += int(float(r.get("qtd_gravidade_grave") or 0))
        if tipo == "NOTIFICACAO":  # registro incompleto: fica só na contagem mensal
            continue
        hora = r.get("hora_sinistro", "")[:2]
        if re.fullmatch(r"\d\d", hora):
            cont["hora"][(ano, r.get("dia_da_semana", "").strip(), hora)] += 1
        cont["tipo"][(ano, (r.get("tp_sinistro_primario") or "NÃO INFORMADO").strip())] += 1
        via = " ".join((r.get("logradouro") or "").split()).upper()
        if via:
            cont["via"][(ano, via)] += 1
        la, lo = numero(r.get("latitude", "")), numero(r.get("longitude", ""))
        if la is not None and lo is not None and -24.2 < la < -23.0 and -48.2 < lo < -46.9:
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


def coletar(acesso_em: date, destino: Path = DESTINO) -> list[int]:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / "manifesto.json"
    man = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"anos": {}}
    feitos = []
    with httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 SorocabaEmDados/1.0"}, event_hooks={"request": [so_host_confiavel]}) as c:
        recursos = json.loads(baixar(c, CKAN))["result"]["resources"]
        por_mes: dict[tuple[int, int], str] = {}
        for r in recursos:
            m = re.search(r"sinistros_(\d\d)-(\d{4})\.csv", r.get("url", ""))
            if m:
                por_mes[(int(m.group(2)), int(m.group(1)))] = r["url"]
        if not por_mes:
            raise ValueError("nenhum arquivo mensal de sinistros no catálogo")
        for ano in range(acesso_em.year - ANOS_ATRAS, acesso_em.year + 1):
            pasta = destino / str(ano)
            if ano < acesso_em.year - ANOS_RECALCULADOS + 1 and (pasta / "mensal.csv").exists():
                continue
            meses = sorted(m for (a, m) in por_mes if a == ano)
            if not meses:
                continue
            cont = {t: Counter() for t in TABELAS}
            total = 0
            for mes in meses:
                total += agregar_mes(baixar(c, por_mes[(ano, mes)]).decode("latin-1"), ano, mes, cont)
            if not total:
                raise ValueError(f"nenhum sinistro de Sorocaba em {ano}")
            pasta.mkdir(exist_ok=True)
            hashes = {}
            for t, campos in TABELAS.items():
                texto = csv_texto(campos, cont[t], mensal=(t == "mensal"))
                (pasta / f"{t}.csv").write_text(texto, encoding="utf-8")
                hashes[t] = hashlib.sha256(texto.encode("utf-8")).hexdigest()
            man["anos"][str(ano)] = {"meses": meses, "registros": total, "sha256_csv": hashes, "coletado_em": acesso_em.isoformat()}
            feitos.append(ano)
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
