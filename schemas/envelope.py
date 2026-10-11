from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class Flag(StrEnum):
    REAL = "real"
    ESTIMATIVA = "estimativa"
    PENDENTE = "pendente"


class Granularidade(StrEnum):
    SEMANAL = "semanal"
    MENSAL = "mensal"
    ANUAL = "anual"


class _Estrito(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Fonte(_Estrito):
    nome: str
    url: str
    licenca: str
    acesso_em: date

    @field_validator("url")
    @classmethod
    def _esquema_permitido(cls, url: str) -> str:
        if not url.startswith(("http://", "https://", "ftp://")):
            raise ValueError("fonte.url com esquema não permitido")
        return url


class Referencia(_Estrito):
    inicio: date
    fim: date
    granularidade: Granularidade

    @field_validator("fim")
    @classmethod
    def _fim_apos_inicio(cls, fim: date, info: Any) -> date:
        inicio = info.data.get("inicio")
        if inicio and fim < inicio:
            raise ValueError("referencia.fim anterior a referencia.inicio")
        return fim


class Cobertura(_Estrito):
    municipio: str
    ibge: str
    uf: str


class Qualidade(_Estrito):
    flag: Flag
    n_registros: int
    notas: list[str] = []


class Envelope(_Estrito):
    schema_version: str = "1.0"
    painel: str
    fonte: Fonte
    referencia: Referencia
    cobertura: Cobertura
    qualidade: Qualidade
    dados: list[dict[str, str | int | float | bool | None]]

    @field_validator("dados")
    @classmethod
    def _registros_planos(cls, dados: list[dict]) -> list[dict]:
        for registro in dados:
            for chave, valor in registro.items():
                if isinstance(valor, (dict, list)):
                    raise ValueError(f"registro com aninhamento em '{chave}'")
        return dados

    def model_post_init(self, __context: Any) -> None:
        if self.qualidade.n_registros != len(self.dados):
            raise ValueError("qualidade.n_registros diverge de len(dados)")
