# Garante sys.path para:
# - diretório executável (dist/UploadAssistant)
# - APP_DIR (onde o ua_gui cria data/__init__.py e data/config.py)
# - third_party/Upload-Assistant (para src/, cogs/, etc.)
import os, sys
from pathlib import Path

def _safe_insert(p):
    if p and str(p) not in sys.path:
        sys.path.insert(0, str(p))

# base do executável (dist/UploadAssistant)
if getattr(sys, "frozen", False):
    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
else:
    base = Path.cwd()

# diretório raiz do app (dist/UploadAssistant)
app_root = base if base.is_dir() else base.parent

# APP_DIR padrão (igual ao ua_gui.py em modo frozen: %LOCALAPPDATA%/UploadAssistant) – aqui só garantimos o root
# O import de data.config vem do APP_DIR, mas o ua_gui.py cria o pacote.
# No mínimo, mantenha app_root e third_party no caminho para o UA.
ua_dir = app_root / "third_party" / "Upload-Assistant"

_safe_insert(app_root)
_safe_insert(ua_dir)
