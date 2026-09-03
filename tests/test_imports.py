"""Modüllerin tek başına import edilebildiğini doğrular.

Dairesel import'lar sinsi: test paketi modülleri şanslı bir sırada yüklerse
sorun görünmez, ama kullanıcı `python -c "from app.agents...."` yazdığında
program açılmadan patlar. Her giriş noktasını ayrı süreçte deniyoruz.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

MODULES = [
    "app.adapters",
    "app.adapters.registry",
    "app.adapters.llm_extract",
    "app.adapters.probe",
    "app.agents.client",
    "app.agents.extract_jobs",
    "app.agents.detect_ats",
    "app.discovery.api",
    "app.discovery.service",
    "app.discovery.sources",
    "app.web_search",
    "app.cli",
    "app.main",
    "app.pipeline.crawl",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_standalone(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"{module} tek başına import edilemedi:\n{result.stderr}"
