"""
Helpers to keep subprocess-based tools quiet on Windows.

PyInstaller embutido em modo GUI não possui console. Quando scripts
spawnam executáveis de linha de comando (ffmpeg, mediainfo, mkbrr, etc.)
o Windows cria um console efêmero para cada processo, o que resulta em
“janelas piscando”. Reutilizamos esses kwargs em todos os subprocessos
para instruir o Windows a não anexar/abrir consoles.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import subprocess as _subprocess

    _NO_CONSOLE_KWARGS: dict[str, object] = {
        "creationflags": _subprocess.CREATE_NO_WINDOW,
    }
else:  # pragma: no cover - outros sistemas não precisam do ajuste
    _NO_CONSOLE_KWARGS = {}


def no_console_kwargs(overrides: dict[str, object] | None = None) -> dict[str, object]:
    """
    Retorna kwargs para subprocess/asyncio.create_subprocess_* que evitam
    consoles extras no Windows. Em outras plataformas retorna {}.
    """
    if not overrides:
        return dict(_NO_CONSOLE_KWARGS)
    merged = dict(_NO_CONSOLE_KWARGS)
    merged.update(overrides)
    return merged
