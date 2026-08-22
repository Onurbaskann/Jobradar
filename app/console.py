"""Terminal çıktısı için ortak konsol.

Ayrı bir modül olmasının sebebi teknik: kodlama düzeltmesinin *import zamanında*
ve Console oluşturulmadan önce çalışması gerekiyor; bunu cli.py içinde import
satırlarının arasına koymak dosyayı okunmaz hale getiriyordu.
"""

from __future__ import annotations

import sys

from rich.console import Console

# Windows konsolu varsayılan olarak cp1254 gibi bir kod sayfası kullanır: hem
# Türkçe karakterler bozulur hem de "✓" gibi işaretler UnicodeEncodeError ile
# komutu çökertir.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):  # yönlendirilmiş veya kapalı akışlar
            pass

console = Console()
