"""Classe FII.

Um FII não é uma ação com dividendo mensal. O **P/VP** é o indicador central (um fundo publica
o patrimônio contábil por cota todo mês — comprar a 0,88× é objetivamente diferente de comprar
a 1,25×), e a **composição do ativo** revela o que o fundo de fato é.

O teste que mais importa é `test_a_composicao_denuncia_o_que_o_nome_esconde`: a GARE11 se chama
"FII Guardial LOGÍSTICA" e tem 70% do ativo em cotas de OUTROS FIIs.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.ativos.fii import FII, _composicao
from app.ingest.cvm_fii import ISIN_EXCECOES, _ticker_do_isin


def _painel(**kw) -> pd.DataFrame:
    base = {
        "ticker": "XPTO11", "cnpj": "00.000.000/0001-00",
        "dt_refer": pd.Timestamp("2025-12-01"), "dt_entrega": pd.Timestamp("2026-01-15"),
        "nome": "FII TESTE", "isin": "BRXPTOCTF001",
        "vp_cota": 10.0, "patrimonio": 1_000_000_000.0, "cotas": 100_000_000.0,
        "cotistas": 50_000.0, "ativo_total": 1_050_000_000.0,
        "valor_imoveis": 900_000_000.0, "valor_papel": 50_000_000.0,
        "valor_cotas_fii": 50_000_000.0, "passivo": 20_000_000.0,
    }
    base.update(kw)
    return pd.DataFrame([base])


def _rend(total: float) -> dict:
    idx = pd.date_range(end=pd.Timestamp.now(), periods=12, freq="30D")
    return {"XPTO11": pd.Series([total / 12] * 12, index=idx)}


# --------------------------------------------------------------- P/VP


def test_o_pvp_e_o_indicador_central_do_FII():
    """Um fundo publica o patrimônio por cota. Comprar a 0,88× o patrimônio é comprar R$ 1,00
    de imóvel por R$ 0,88 — uma clareza que não existe em ação operacional."""
    av = FII(_painel(vp_cota=10.0), _rend(1.0)).avaliar("XPTO11", 8.80, 0.10)

    assert av.metrica("p_vp") == pytest.approx(0.88)
    assert av.metrica("vpa") == pytest.approx(10.0)


def test_teto_do_FII_vem_do_rendimento_anual_sobre_a_SUA_meta():
    av = FII(_painel(), _rend(1.20)).avaliar("XPTO11", 10.00, 0.10)

    assert av.teto.valor == pytest.approx(12.00)   # 1,20 ÷ 10%
    assert av.abaixo_do_teto is True


def test_pvp_alto_vira_ressalva():
    av = FII(_painel(vp_cota=10.0), _rend(1.0)).avaliar("XPTO11", 12.50, 0.10)

    assert av.metrica("p_vp") == pytest.approx(1.25)
    assert any("por R$ 1,00 de patrimônio" in a for a in av.alertas)


# --------------------------------------------------------------- composição


def test_a_composicao_denuncia_o_que_o_nome_esconde():
    """A GARE11 se chama "FII Guardial LOGÍSTICA". A composição real: 70% em cotas de OUTROS
    FIIs, 13% em papel, 17% em imóvel. Quem compra achando que tem galpão tem, na verdade, um
    fundo de fundos com perna de crédito — e paga DUAS camadas de taxa.
    """
    av = FII(
        _painel(valor_imoveis=429e6, valor_papel=355e6, valor_cotas_fii=1635e6),
        _rend(0.91),
    ).avaliar("XPTO11", 8.15, 0.10)

    assert av.metrica("pct_fii") == pytest.approx(0.676, abs=0.01)
    assert av.metrica("pct_imovel") == pytest.approx(0.177, abs=0.01)
    assert any("COTAS DE OUTROS FIIs" in a for a in av.alertas)
    assert any("duas camadas de taxa" in a for a in av.alertas)


def test_fundo_de_papel_e_risco_de_CREDITO_nao_de_vacancia():
    """O BTHF11 é 100% CRI. O rendimento segue IPCA/CDI, não aluguel — e o que pode dar errado
    é inadimplência, não imóvel vazio. São teses completamente diferentes."""
    av = FII(
        _painel(valor_imoveis=0.0, valor_papel=1000e6, valor_cotas_fii=0.0),
        _rend(1.17),
    ).avaliar("XPTO11", 9.04, 0.10)

    assert av.metrica("pct_papel") == pytest.approx(1.0)
    assert any("risco é de CRÉDITO" in a for a in av.alertas)


def test_a_SPE_conta_como_imovel():
    """Muitos FIIs detêm os prédios via sociedade de propósito específico — o imóvel aparece
    como "Ações/Cotas de Sociedades com Atividades de FII", não como imóvel direto. Sem
    incluí-las, um fundo de tijolo puro é classificado como outra coisa."""
    u = pd.Series({"valor_imoveis": 1000.0, "valor_papel": 0.0, "valor_cotas_fii": 0.0})
    assert _composicao(u)["imovel"] == pytest.approx(1.0)

    vazio = pd.Series({"valor_imoveis": 0.0, "valor_papel": 0.0, "valor_cotas_fii": 0.0})
    assert _composicao(vazio) == {}


# --------------------------------------------------------------- ISIN


def test_o_isin_costuma_embutir_o_ticker():
    assert _ticker_do_isin("BRGARECTF001") == "GARE11"
    assert _ticker_do_isin("BRHFOFCTF002") == "HFOF11"


def test_mas_nem_sempre_e_a_excecao_e_explicita():
    """O BTHF11 é BR0EI9CTF007 — prefixo "0EI9", não "BTHF". Derivar cegamente inventaria um
    ticker que não existe; as exceções ficam registradas, e o que não mapeia é DENUNCIADO."""
    assert _ticker_do_isin("BR0EI9CTF007") == "BTHF11"
    assert "BR0EI9CTF007" in ISIN_EXCECOES

    assert _ticker_do_isin("BR1234CTF007") is None  # prefixo não-alfabético → não inventa
    assert _ticker_do_isin(None) is None
    assert _ticker_do_isin("XX") is None


def test_fii_nao_mapeado_diz_que_nao_sabe():
    av = FII(_painel(), _rend(1.0)).avaliar("NAOEXISTE11", 10.0, 0.10)

    assert av.teto is None
    assert av.sem_criterio
    assert "não mapeado" in av.sem_criterio


# --------------------------------------------------------------- o que NÃO sabemos


def test_vacancia_e_declarada_como_indisponivel_e_nao_inventada():
    """A CVM não publica vacância — ela vive no relatório gerencial (FNET), que não é dado
    estruturado. O sistema DIZ que não sabe."""
    impl = FII(_painel(), _rend(1.0))

    assert "vacancia" not in impl.metricas_disponiveis()
    av = impl.avaliar("XPTO11", 10.0, 0.10)
    assert any("vacância: não disponível" in a for a in av.alertas)
