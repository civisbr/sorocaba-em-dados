"""Guarda, sem transformar, as respostas das APIs do IBGE usadas no perfil da cidade."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote

import httpx

API = "https://servicodados.ibge.gov.br/api"
HOST = "servicodados.ibge.gov.br"
MUNICIPIO = "3552205"
LIMITE_BYTES = 2 * 1024 * 1024
DESTINO = Path(__file__).resolve().parent.parent / "data" / "raw" / "ibge" / "perfil"
LOC = f"N6[{MUNICIPIO}]"

# O VAB por setor vem vazio ("...") para 2022 e 2023; 2021 é o último ano com valores.
CONSULTAS = {
    "localidade": f"/v1/localidades/municipios/{MUNICIPIO}",
    "censo_2022": f"/v3/agregados/4714/periodos/2022/variaveis/93|614|6318?localidades={LOC}",
    "estimativa": f"/v3/agregados/6579/periodos/-1/variaveis/9324?localidades={LOC}",
    "pib": f"/v3/agregados/5938/periodos/-6/variaveis/37|553|552|497|530|496?localidades={LOC}",
    "vab_2021": f"/v3/agregados/5938/periodos/2021/variaveis/498|513|517|6575|525?localidades={LOC}",
}


def so_host_confiavel(r: httpx.Response) -> None:
    if r.url.scheme != "https" or r.url.host != HOST:
        raise ValueError(f"resposta fora de https://{HOST}: {r.url}")


def baixar(client: httpx.Client, caminho: str, tentativas: int = 4) -> bytes:
    url = API + quote(caminho, safe="/?=&|[]:%")
    for n in range(tentativas):
        try:
            r = client.get(url)
            r.raise_for_status()
            if len(r.content) > LIMITE_BYTES:
                raise ValueError(f"{caminho} acima do limite esperado")
            return r.content
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            permanente = isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500
            if permanente or n == tentativas - 1:
                raise
            time.sleep(2**n * 2)
    raise RuntimeError("inalcançável")


def coletar(acesso_em: date, destino: Path = DESTINO) -> list[str]:
    destino.mkdir(parents=True, exist_ok=True)
    antigo = json.loads((destino / "manifesto.json").read_text(encoding="utf-8")) if (destino / "manifesto.json").exists() else {}
    novo = {"acesso_em": acesso_em.isoformat(), "arquivos": {}}
    mudou = []
    with httpx.Client(timeout=60, follow_redirects=True, event_hooks={"response": [so_host_confiavel]}) as c:
        corpos = {nome: baixar(c, caminho) for nome, caminho in CONSULTAS.items()}
    for nome, corpo in corpos.items():
        # Reserializa para o arquivo ser estável; JSON inválido aborta aqui.
        texto = json.dumps(json.loads(corpo), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        sha = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        novo["arquivos"][nome] = {"url": API + CONSULTAS[nome], "sha256": sha}
        if antigo.get("arquivos", {}).get(nome, {}).get("sha256") != sha:
            (destino / f"{nome}.json").write_text(texto, encoding="utf-8")
            mudou.append(nome)
    # Sem resposta nova o manifesto fica intacto, para não gerar commit só pela data de acesso.
    if mudou or not antigo:
        (destino / "manifesto.json").write_text(json.dumps(novo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return mudou


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("atualizados:", coletar(args.acesso_em) or "nenhum")


if __name__ == "__main__":
    main()
