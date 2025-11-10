# ua_gui.spec — Windows / PyInstaller 6.x
import os
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
    collect_all,
)

ROOT = Path.cwd().resolve()
APP_NAME = "SamUploadAssistant"
MAIN_SCRIPT = str(ROOT / "ua_gui.py")

RES_DIR = ROOT / "resources"
UA_DIR  = ROOT / "third_party" / "Upload-Assistant"
HOOKS_DIR = ROOT / "pyi_hooks"

# Utilitário simples para acrescentar listas evitando duplicatas.
def _extend_unique(target, items):
    for item in items:
        if item not in target:
            target.append(item)

# ---------------- Datas que já tínhamos
datas = []
if RES_DIR.exists():
    datas.append((str(RES_DIR), "resources"))
if UA_DIR.exists():
    datas.append((str(UA_DIR), "third_party/Upload-Assistant"))
for fn in ["icon.ico", "icon.png", "logo.png"]:
    p = ROOT / fn
    if p.exists():
        datas.append((str(p), "."))

# ---------------- **NOVO**: dados exigidos por libs
# babelfish precisa de babelfish/data/*.txt (iso-3166-1.txt etc.)
# --- Inclui babelfish/data inteira (corrige FileNotFoundError iso-3166-1.txt)
import importlib.util as _imp

try:
    _bf_spec = _imp.find_spec("babelfish")
    if _bf_spec and _bf_spec.origin:
        _bf_pkg_dir = Path(_bf_spec.origin).parent
        _bf_data_dir = _bf_pkg_dir / "data"
        if _bf_data_dir.exists():
            # Copia a pasta data inteira para dentro de babelfish/data no bundle
            datas.append((str(_bf_data_dir), "babelfish/data"))
        else:
            # fallback: ainda tenta via collect_data_files
            from PyInstaller.utils.hooks import collect_data_files as _cdf
            datas += _cdf("babelfish", subdir="data", include_py_files=False)
except Exception:
    # fallback agressivo
    from PyInstaller.utils.hooks import collect_data_files as _cdf
    datas += _cdf("babelfish", subdir="data", include_py_files=False)

datas += collect_data_files("guessit", includes=["guessit/rules/**/*.yml","guessit/rules/**/*.yaml"], include_py_files=False)
datas += collect_data_files("langcodes", include_py_files=False)
datas += collect_data_files("certifi", includes=["certifi/cacert.pem"], include_py_files=False)



# guessit carrega regras YAML em runtime
datas += collect_data_files("guessit", includes=["guessit/rules/**/*.yml", "guessit/rules/**/*.yaml"], include_py_files=False)

# langcodes tem tabelas internas usadas em runtime
datas += collect_data_files("langcodes", include_py_files=False)

# certifi (cadeia de certificados usada por requests/httpx)
# ---------------- Dependências do Upload-Assistant (requirements.txt)
# Usa collect_all para garantir que código + dados/binaries sejam levados junto.
binaries = []
COLLECT_ALL_PACKAGES = [
    "aiofiles",
    "aiohttp",
    "anitopy",
    "bbcode",
    "bs4",           # beautifulsoup4
    "bencodepy",
    "cli_ui",
    "click",
    "cloudscraper",
    "deluge_client",
    "discord",
    "ffmpeg",        # ffmpeg-python
    "guessit",
    "httpx",
    "jinja2",
    "langcodes",
    "lxml",
    "nest_asyncio",
    "packaging",
    "PIL",
    "psutil",
    "pycountry",
    "pyimgbox",
    "pymediainfo",
    "pyotp",
    "oxipng",        # pyoxipng
    "pyparsebluray",
    "qbittorrentapi",
    "requests",
    "rich",
    "tmdbsimple",
    "torf",
    "tqdm",
    "transmission_rpc",
    "unidecode",
    "urllib3",
]

for pkg in COLLECT_ALL_PACKAGES:
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    _extend_unique(datas, pkg_datas)
    _extend_unique(binaries, pkg_binaries)
    _extend_unique(pkg_hiddenimports, pkg_hiddenimports)

# (opcional) tzdata — às vezes httpx/stdlib usam; raro, mas seguro
try:
    datas += collect_data_files("tzdata", include_py_files=False)
except Exception:
    pass

# ---------------- Runtime hooks
runtime_hooks = []
rthook_bencode = HOOKS_DIR / "rthook-bencode_alias.py"
rthook_syspath = HOOKS_DIR / "rthook-syspath_ua.py"
if rthook_bencode.exists():
    runtime_hooks.append(str(rthook_bencode))
if rthook_syspath.exists():
    runtime_hooks.append(str(rthook_syspath))

# ---------------- Hiddenimports
hiddenimports = [
    "aiofiles",
    "aiohttp",
    "anitopy",
    "bbcode",
    "bs4",
    "bencode",           # resolvido via runtime hook -> bencodepy
    "cli_ui",
    "click",
    "cloudscraper",
    "deluge_client",
    "discord",
    "ffmpeg",
    "ffmpeg.nodes",
    "guessit",
    "httpx",
    "jinja2",
    "jinja2.ext",
    "jinja2.loaders",
    "jinja2.filters",
    "jinja2.utils",
    "langcodes",
    "lxml",
    "lxml.etree",
    "lxml._elementpath",
    "nest_asyncio",
    "packaging",
    "PIL",
    "PIL.Image",
    "psutil",
    "pycountry",
    "pyimgbox",
    "pymediainfo",
    "pyotp",
    "pyoxipng",
    "pyparsebluray",
    "qbittorrentapi",
    "requests",
    "rich",
    "rich.console",
    "rich.table",
    "rich.panel",
    "tmdbsimple",
    "torf",
    "tqdm",
    "transmission_rpc",
    "unidecode",
    "urllib3",
]
hiddenimports += collect_submodules("discord")
hiddenimports += collect_submodules("guessit")
hiddenimports += ["babelfish"]
hiddenimports += collect_submodules("babelfish.converters")
# inclui o módulo e quaisquer submódulos (por segurança)
hiddenimports += ['oxipng']
hiddenimports += collect_submodules('oxipng')
block_cipher = None

a = Analysis(
    [MAIN_SCRIPT],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],                 # usamos *runtime* hooks, não "hook-*.py"
    runtime_hooks=runtime_hooks,
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Ícone
_icon = None
if (ROOT / "resources" / "icon.ico").exists():
    _icon = str(ROOT / "resources" / "icon.ico")
elif (ROOT / "icon.ico").exists():
    _icon = str(ROOT / "icon.ico")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # GUI
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
