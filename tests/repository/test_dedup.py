from repository.dedup import compute_fingerprint, is_similar, normalize_description


def test_normalize_description_lowercases_strips_accents_and_punctuation():
    assert normalize_description("Café  com Açúcar!!") == "cafe com acucar"


def test_compute_fingerprint_is_deterministic():
    a = compute_fingerprint(10.5, "saida", "cafe padaria")
    b = compute_fingerprint(10.5, "saida", "cafe padaria")

    assert a == b


def test_compute_fingerprint_changes_when_valor_changes():
    base = compute_fingerprint(10.5, "saida", "cafe padaria")
    changed = compute_fingerprint(20.0, "saida", "cafe padaria")

    assert base != changed


def test_compute_fingerprint_changes_when_tipo_changes():
    base = compute_fingerprint(10.5, "saida", "cafe padaria")
    changed = compute_fingerprint(10.5, "entrada", "cafe padaria")

    assert base != changed


def test_compute_fingerprint_changes_when_descricao_normalizada_changes():
    base = compute_fingerprint(10.5, "saida", "cafe padaria")
    changed = compute_fingerprint(10.5, "saida", "uber viagem")

    assert base != changed


def test_is_similar_identical_strings_is_true():
    assert is_similar("cafe padaria", "cafe padaria") is True


def test_is_similar_unrelated_strings_is_false():
    assert is_similar("cafe padaria", "uber viagem") is False


def test_is_similar_light_ocr_noise_is_true():
    assert is_similar("cafe padaria centro", "cafe padria centro") is True
