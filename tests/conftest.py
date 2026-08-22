import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Geliştirici .env'i Docker içinden host Ollama'ya bağlanabilir. Birim testleri
# ise sabit olarak yerel mock adresini kullanır; ortam ayarı test sözleşmesini
# değiştirmemeli.
os.environ["OLLAMA_URL"] = "http://127.0.0.1:11434"


@pytest.fixture
def fixture_json():
    def _load(name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def fixture_text():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _load
