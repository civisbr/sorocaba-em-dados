import hashlib
import io
import json
import zipfile

import pytest

from scripts import fetch_inep
from scripts.build_escolas import RAIZ, decimal


def test_decimal_trata_traco_como_ausente():
    assert decimal("-") is None and decimal("") is None and decimal("6.2") == 6.2


def zip_com(nome, conteudo, md5_txt=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"pasta/{nome}", conteudo)
        z.writestr("pasta/md5_x.txt", md5_txt or f"{hashlib.md5(conteudo).hexdigest()} *{nome}\n")
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_md5_confere(tmp_path):
    z = zip_com("a.csv", b"abc")
    info = fetch_inep.membro_unico(z, r".*\.csv")
    assert fetch_inep.extrair_verificando(z, info, tmp_path / "o") == hashlib.md5(b"abc").hexdigest()


def test_md5_divergente_quebra(tmp_path):
    z = zip_com("a.csv", b"abc", md5_txt="00000000000000000000000000000000 *a.csv\n")
    with pytest.raises(ValueError, match="md5"):
        fetch_inep.extrair_verificando(z, fetch_inep.membro_unico(z, r".*\.csv"), tmp_path / "o")


def test_membro_ambiguo_quebra():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", "x")
        z.writestr("b.csv", "y")
    with pytest.raises(ValueError, match="esperava 1 membro"):
        fetch_inep.membro_unico(zipfile.ZipFile(buf), r".*\.csv")


def test_censo_filtra_municipio_e_exige_colunas(tmp_path):
    cab = ";".join(fetch_inep.CENSO_COLUNAS + ["CO_MUNICIPIO"])
    def linha(mun):
        return ";".join(["x"] * len(fetch_inep.CENSO_COLUNAS) + [mun])
    f = tmp_path / "c.csv"
    f.write_text("\n".join([cab, linha("3552205"), linha("3550308")]) + "\n", encoding="latin-1")
    assert fetch_inep.filtrar_censo(f).count("\n") == 2
    f.write_text("A;B\n1;2\n", encoding="latin-1")
    with pytest.raises(ValueError, match="colunas ausentes"):
        fetch_inep.filtrar_censo(f)


def test_tls_usa_intermediario_versionado():
    assert fetch_inep.CERT_INTERMEDIARIO.exists()
    fetch_inep.contexto_tls()


def test_dado_publicado_e_coerente():
    env = json.loads((RAIZ / "data/public/escolas.json").read_text(encoding="utf-8"))
    assert env["qualidade"]["n_registros"] == len(env["dados"])
    ids = [e["co_inep"] for e in env["dados"]]
    assert len(ids) == len(set(ids))
    for e in env["dados"]:
        for k, v in e.items():
            if k.startswith("ideb_"):
                assert v is None or 0 <= v <= 10
    assert [e["escola"] for e in env["dados"]] == sorted((e["escola"] for e in env["dados"]))


def test_tls_exige_cadeia_ate_raiz_e_pem_conhecido():
    import hashlib, ssl
    ctx = fetch_inep.contexto_tls()
    assert not ctx.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
    der = ssl.PEM_cert_to_DER_cert(fetch_inep.CERT_INTERMEDIARIO.read_text())
    assert hashlib.sha256(der).hexdigest() == "e10747d4da7bab09cba9952f019d3534cb9fba070bf13d8791b1699cd2ff59dd"


def test_hook_recusa_host_ou_esquema_diferente():
    import httpx
    for url in ("http://download.inep.gov.br/x", "https://outro.exemplo/x"):
        with pytest.raises(ValueError):
            fetch_inep.so_host_confiavel(httpx.Response(200, request=httpx.Request("GET", url)))


def test_referencia_valida_quando_censo_e_mais_novo_que_ideb(tmp_path):
    import shutil
    from scripts.build_escolas import construir

    raw = tmp_path / "inep"
    shutil.copytree(RAIZ / "data/raw/inep", raw)
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    man["arquivos"]["censo_escolar"]["ano"] = 2027
    (raw / "manifesto.json").write_text(json.dumps(man), encoding="utf-8")
    ref = construir(raw).referencia
    assert ref.inicio <= ref.fim


def test_builds_deterministicos(tmp_path):
    from scripts.build_combustivel import construir as c1
    from scripts.build_escolas import construir as c2

    for fn, d in ((c1, "anp"), (c2, "inep")):
        assert fn(RAIZ / "data/raw" / d).model_dump_json() == fn(RAIZ / "data/raw" / d).model_dump_json()
