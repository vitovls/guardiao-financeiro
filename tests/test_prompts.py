from prompts import (
    TRANSACTION_SCHEMA,
    build_document_extraction_prompt,
    build_text_extraction_prompt,
)


def test_build_text_extraction_prompt_contains_date_text_and_flag():
    prompt = build_text_extraction_prompt("2026-07-26", "gastei 30 no mercado")

    assert "2026-07-26" in prompt
    assert "gastei 30 no mercado" in prompt
    assert "e_transacao" in prompt


def test_build_document_extraction_prompt_contains_label_and_schema():
    prompt = build_document_extraction_prompt("imagem")

    assert "imagem" in prompt
    assert TRANSACTION_SCHEMA in prompt
