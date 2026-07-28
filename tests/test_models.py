from datetime import date

from models import DEFAULT_CATEGORIA, Transacao


def _kwargs(**overrides):
    base = dict(data=date(2026, 6, 15), descricao="cafe", valor=8.0, tipo="saida", categoria="alimentacao")
    base.update(overrides)
    return base


def test_categoria_vazia_vira_categoria_padrao():
    t = Transacao(**_kwargs(categoria=""))
    assert t.categoria == DEFAULT_CATEGORIA


def test_categoria_omitida_vira_categoria_padrao():
    kwargs = _kwargs()
    del kwargs["categoria"]
    t = Transacao(**kwargs)
    assert t.categoria == DEFAULT_CATEGORIA


def test_categoria_preenchida_permanece_inalterada():
    t = Transacao(**_kwargs(categoria="alimentacao"))
    assert t.categoria == "alimentacao"
