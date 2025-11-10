#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import os
import re
import sys
import tarfile
import zipfile
import shutil
import stat
import subprocess
import threading
import time
import runpy
import traceback
import ast
import json
import math
import importlib
import requests
import multiprocessing
from collections import deque
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Callable, Sequence, Any, Deque
from urllib.parse import urlparse
import zipfile, tarfile
import faulthandler

# ---------------------------
# Bundle/paths
# ---------------------------

def is_frozen() -> bool:
    return getattr(sys, "frozen", False) is True and hasattr(sys, "_MEIPASS")

def running_frozen() -> bool:
    return getattr(sys, "frozen", False)

def get_bundle_dir() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent

def get_app_dir() -> Path:
    if is_frozen():
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Local")
            return Path(base) / "UploadAssistant"
        else:
            return Path.home() / ".local" / "share" / "UploadAssistant"
    else:
        return Path(__file__).resolve().parent / ".appdata"

BUNDLE_DIR = get_bundle_dir()
APP_DIR = get_app_dir()
DATA_DIR = APP_DIR / "data"
RES_DIR = BUNDLE_DIR / "resources"
LOG_DIR = APP_DIR / "logs"
BIN_DIR = APP_DIR / "bin"

def ensure_dirs() -> None:
    third_party_dir = APP_DIR / "third_party"
    for p in [APP_DIR, DATA_DIR, LOG_DIR, BIN_DIR, third_party_dir]:
        p.mkdir(parents=True, exist_ok=True)

def log_path(name: str = "ua_gui.log") -> Path:
    ensure_dirs()
    return LOG_DIR / name

def write_log(message: str, name: str = "ua_gui.log") -> None:
    try:
        with open(log_path(name), "a", encoding="utf-8") as f:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass

# ---------------------------
# UI: customtkinter se disponível; fallback tkinter
# ---------------------------

USE_CTK = False
try:
    import customtkinter as ctk
    USE_CTK = True
except Exception:
    import tkinter as ctk  # type: ignore
    from tkinter import filedialog, messagebox

if USE_CTK:
    from tkinter import filedialog, messagebox

PIL_OK = False
try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False

# ---------------------------
# FFmpeg/MediaInfo discovery & install (offline-first + online com progresso)
# ---------------------------

def which(cmd: str) -> Optional[str]:
    out = shutil.which(cmd)
    if out:
        return out
    if os.name == "nt" and not cmd.lower().endswith(".exe"):
        out = shutil.which(cmd + ".exe")
        if out:
            return out
    # BIN_DIR
    exes = [cmd] + ([cmd + ".exe"] if os.name == "nt" else [])
    for e in exes:
        p = BIN_DIR / e
        if p.exists():
            return str(p)
        for root, _, files in os.walk(BIN_DIR):
            if e in files:
                return str(Path(root) / e)
    return None

def make_executable(path: Path) -> None:
    if os.name != "nt":
        try:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass

def extract_zip_to(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(src, "r") as zf:
        zf.extractall(dst)

def extract_tar_to(src: Path, dst: Path) -> None:
    with tarfile.open(src, "r:*") as tf:
        tf.extractall(dst)

def install_from_archive(archive: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if archive.suffix.lower() == ".zip":
        extract_zip_to(archive, target_dir)
    else:
        extract_tar_to(archive, target_dir)

def try_register_bins_from(folder: Path) -> None:
    if not folder.exists():
        return
    for root, _, files in os.walk(folder):
        for f in files:
            p = Path(root) / f
            if os.name != "nt":
                make_executable(p)
    os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")

def find_ffmpeg_binaries() -> Tuple[Optional[str], Optional[str]]:
    return which("ffmpeg"), which("ffprobe")

def find_mediainfo_binary() -> Optional[str]:
    return which("mediainfo")

def prepare_ffmpeg_offline(progress: Callable[[str, float, str], None] | None = None) -> bool:
    try:
        if progress: progress("Verificando FFmpeg (offline)", 0.0, "")
        f, p = find_ffmpeg_binaries()
        if f and p:
            if progress: progress("FFmpeg encontrado", 1.0, "")
            return True
        ffmpeg_dir = RES_DIR / "ffmpeg"
        if ffmpeg_dir.exists():
            if progress: progress("Registrando FFmpeg em resources/ffmpeg", 0.2, "")
            try_register_bins_from(ffmpeg_dir)
            f, p = find_ffmpeg_binaries()
            if f and p:
                if progress: progress("FFmpeg OK (resources)", 1.0, "")
                return True
            # tenta extrair se houver pacotes
            archives = [x for x in ffmpeg_dir.iterdir()
                        if x.is_file() and (x.suffix.lower() in {".zip", ".gz", ".xz", ".tar"}
                        or x.name.endswith(".tar.gz") or x.name.endswith(".tar.xz"))]
            if archives:
                target = BIN_DIR / "ffmpeg"
                target.mkdir(parents=True, exist_ok=True)
                for i, arc in enumerate(archives, 1):
                    if progress: progress(f"Extraindo FFmpeg ({i}/{len(archives)})", 0.3 + 0.5*(i/len(archives)), arc.name)
                    try:
                        install_from_archive(arc, target)
                    except Exception as e:
                        write_log(f"Falha ao extrair {arc}: {e}")
                try_register_bins_from(target)
                f, p = find_ffmpeg_binaries()
                if f and p:
                    if progress: progress("FFmpeg OK (extraído)", 1.0, "")
                    return True
        if progress: progress("FFmpeg não encontrado offline", 1.0, "")
        return False
    except Exception as e:
        write_log(f"prepare_ffmpeg_offline erro: {e}")
        if progress: progress("Erro FFmpeg offline", 1.0, str(e))
        return False

def prepare_mediainfo_offline(progress: Callable[[str, float, str], None] | None = None) -> bool:
    try:
        if progress: progress("Verificando MediaInfo (offline)", 0.0, "")
        m = find_mediainfo_binary()
        if m:
            if progress: progress("MediaInfo encontrado", 1.0, "")
            return True
        mi_dir = RES_DIR / "mediainfo"
        if mi_dir.exists():
            if progress: progress("Registrando MediaInfo em resources/mediainfo", 0.2, "")
            try_register_bins_from(mi_dir)
            if find_mediainfo_binary():
                if progress: progress("MediaInfo OK (resources)", 1.0, "")
                return True
            archives = [x for x in mi_dir.iterdir()
                        if x.is_file() and (x.suffix.lower() in {".zip", ".gz", ".xz", ".tar"}
                        or x.name.endswith(".tar.gz") or x.name.endswith(".tar.xz"))]
            if archives:
                target = BIN_DIR / "mediainfo"
                target.mkdir(parents=True, exist_ok=True)
                for i, arc in enumerate(archives, 1):
                    if progress: progress(f"Extraindo MediaInfo ({i}/{len(archives)})", 0.3 + 0.5*(i/len(archives)), arc.name)
                    try:
                        install_from_archive(arc, target)
                    except Exception as e:
                        write_log(f"Falha ao extrair {arc}: {e}")
                try_register_bins_from(target)
                if find_mediainfo_binary():
                    if progress: progress("MediaInfo OK (extraído)", 1.0, "")
                    return True
        if progress: progress("MediaInfo não encontrado offline", 1.0, "")
        return False
    except Exception as e:
        write_log(f"prepare_mediainfo_offline erro: {e}")
        if progress: progress("Erro MediaInfo offline", 1.0, str(e))
        return False

def has_internet() -> bool:
    try:
        import socket
        socket.setdefaulttimeout(2.0)
        socket.gethostbyname("example.com")
        return True
    except Exception:
        return False

# ---- Download genérico com progresso

def detect_archive_type(path: Path) -> str:
    """
    Retorna 'zip' | 'tar' | 'none' baseado no conteúdo.
    """
    try:
        with path.open('rb') as f:
            magic = f.read(6)
        if magic.startswith(b'PK\x03\x04'):
            return 'zip'
    except Exception:
        pass
    try:
        if tarfile.is_tarfile(path):
            return 'tar'
    except Exception:
        pass
    return 'none'

def extract_archive_auto(archive_path: Path, target_dir: Path):
    """
    Extrai ZIP ou TAR.* automaticamente. Levanta erro se não suportado.
    """
    atype = detect_archive_type(archive_path)
    if atype == 'zip':
        with zipfile.ZipFile(archive_path) as z:
            z.extractall(target_dir)
    elif atype == 'tar':
        with tarfile.open(archive_path) as t:
            t.extractall(target_dir)
    else:
        raise RuntimeError(
            f"Arquivo de pacote não suportado: {archive_path.name} "
            f"(tipo detectado: {atype})"
        )

def human(bytes_val: float) -> str:
    units = ["B", "KB", "MB", "GB"]
    i = 0
    while bytes_val >= 1024 and i < len(units)-1:
        bytes_val /= 1024.0
        i += 1
    return f"{bytes_val:.1f} {units[i]}"

def download_file(url: str, out_path: Path, progress: Callable[[str, float, str], None]) -> None:
    """
    Baixa um arquivo com progresso. Lança exceção em erro.
    progress(msg, ratio 0..1, extra) — msg/extra exibidos na UI.
    """
    write_log(f"Baixando: {url}")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = r.headers.get("Content-Length")
        total = int(total) if total and total.isdigit() else None
        chunk = 1048576  # 1MB
        done = 0
        t0 = time.time()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            for data in r.iter_content(chunk_size=chunk):
                if not data:
                    continue
                f.write(data)
                done += len(data)
                if total:
                    ratio = done / total
                    elapsed = max(0.001, time.time() - t0)
                    speed = done / elapsed
                    progress("Baixando", ratio, f"{human(done)} / {human(total)} @ {human(speed)}/s")
                else:
                    # sem tamanho — usa indeterminado (oscila 0..1)
                    phase = (math.sin(time.time()-t0) + 1) / 2
                    progress("Baixando (tamanho não informado)", phase, human(done))

# ---- MediaInfo index parser helpers (MediaArea HTML directory)

MEDIAINFO_BASE = "https://mediaarea.net/download/binary/mediainfo/"

def _fetch_html(url: str) -> str:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text

def _parse_dir_hrefs(html: str) -> List[str]:
    # pega todos os href="..."; o índice é simples
    return re.findall(r'href="([^"]+)"', html, flags=re.I)

def _version_key(ver: str) -> Tuple[int, ...]:
    # "25.09" -> (25, 9); "24.01.1" -> (24,1,1)
    parts = [int(p) for p in re.findall(r'\d+', ver)]
    return tuple(parts)

def _detect_arch() -> Tuple[str, str]:
    import platform
    system = platform.system().lower()   # 'windows' | 'darwin' | 'linux'
    machine = platform.machine().lower() # 'amd64' 'x86_64' 'arm64' 'aarch64'...
    # normaliza
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    elif machine in ("i386", "i686", "x86"):
        arch = "i386"
    else:
        arch = machine or "x86_64"
    return system, arch

def _pick_mediainfo_url() -> Tuple[str, str]:
    """
    Retorna (version, url) para o melhor pacote do sistema atual.
    Levanta Exception se não encontrar artefato adequado.
    """
    sysname, arch = _detect_arch()
    # 1) lista versões
    idx = _fetch_html(MEDIAINFO_BASE)
    hrefs = _parse_dir_hrefs(idx)
    # mantêm apenas subpastas tipo '25.09/'
    vers = [h[:-1] for h in hrefs if re.fullmatch(r'\d{2}\.\d{2}(\.\d+)?/', h)]
    if not vers:
        raise RuntimeError("Não encontrei pastas de versão do MediaInfo no índice.")
    # ordena por versão desc
    vers.sort(key=_version_key, reverse=True)

    for ver in vers:
        listing = _fetch_html(MEDIAINFO_BASE + f"{ver}/")
        files = _parse_dir_hrefs(listing)

        def has(name: str) -> bool:
            return any(f.endswith(name) for f in files)

        # Estratégia por SO:
        if sysname == "windows":
            candidates = []
            if arch == "arm64":
                candidates.append(f"MediaInfo_CLI_{ver}_Windows_ARM64.zip")
            if arch in ("x86_64", "amd64", "x64"):
                candidates.append(f"MediaInfo_CLI_{ver}_Windows_x64.zip")
            # fallback 32-bit
            candidates.append(f"MediaInfo_CLI_{ver}_Windows_i386.zip")
        elif sysname == "linux":
            # Pacotes “Lambda” são zips estáticos (ótimos para embutir)
            if arch == "arm64":
                candidates = [f"MediaInfo_CLI_{ver}_Lambda_arm64.zip"]
            else:
                candidates = [f"MediaInfo_CLI_{ver}_Lambda_x86_64.zip"]
        else:  # macOS (darwin)
            candidates = [
                f"MediaInfo_CLI_{ver}_Mac.dmg",           # aparece com frequência
                f"MediaInfo_CLI_{ver}_Mac_arm64.zip",     # alternativa
                f"MediaInfo_CLI_{ver}_Mac_x86_64.zip",    # alternativa
            ]

        for name in candidates:
            if has(name):
                return ver, MEDIAINFO_BASE + f"{ver}/" + name

    raise RuntimeError("Não encontrei pacote MediaInfo compatível com seu sistema/arquitetura.")

# ---- Instaladores online com progresso/erros

def download_and_install_ffmpeg_online(progress: Callable[[str, float, str], None]) -> Tuple[bool, str]:
    """
    Baixa e instala o FFmpeg estático adequado:
      • Windows: Gyan.dev ZIP 'ffmpeg-release-essentials.zip'
      • Linux:   John Van Sickle estático tar.xz (x86_64/arm64)
      • macOS:   evermeet.cx ZIP (universal) quando disponível; fallback brew-less.
    Extrai corretamente (ZIP/TAR) e registra os binários.
    """
    import tempfile, platform, shutil

    try:
        system = platform.system().lower()
        machine = platform.machine().lower()
        arch = "x86_64" if machine in ("x86_64", "amd64") else ("arm64" if machine in ("arm64", "aarch64") else machine)

        tmpdir = Path(tempfile.mkdtemp(prefix="ua_ffmpeg_"))
        pkg = tmpdir / "ffmpeg_pkg"

        if system == "windows":
            # Gyan.dev essentials build -> ZIP com /bin/ffmpeg.exe e ffprobe.exe
            url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            progress("Baixando FFmpeg (Windows)", 0.05, url)
            download_file(url, pkg, progress)

            progress("Extraindo FFmpeg", 0.90, pkg.name)
            staging = tmpdir / "extract"
            staging.mkdir(parents=True, exist_ok=True)
            extract_archive_auto(pkg, staging)

            # Dentro do ZIP vem uma pasta tipo "ffmpeg-*-essentials_build/bin"
            ffmpeg_bin = None
            ffprobe_bin = None
            for root, dirs, files in os.walk(staging):
                if "ffmpeg.exe" in files:
                    ffmpeg_bin = Path(root) / "ffmpeg.exe"
                if "ffprobe.exe" in files:
                    ffprobe_bin = Path(root) / "ffprobe.exe"
            if not ffmpeg_bin or not ffprobe_bin:
                raise RuntimeError("Não encontrei ffmpeg.exe/ffprobe.exe após a extração.")

            target = BIN_DIR / "ffmpeg"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ffmpeg_bin, target / "ffmpeg.exe")
            shutil.copy2(ffprobe_bin, target / "ffprobe.exe")

            progress("Registrando FFmpeg", 0.97, str(target))
            try_register_bins_from(target)

        elif system == "linux":
            # Builds estáticos (x86_64/arm64) – nomes estáveis
            if arch in ("arm64", "aarch64"):
                url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
            else:
                url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"

            progress("Baixando FFmpeg (Linux estático)", 0.05, url)
            download_file(url, pkg, progress)

            progress("Extraindo FFmpeg", 0.90, pkg.name)
            staging = tmpdir / "extract"
            staging.mkdir(parents=True, exist_ok=True)
            extract_archive_auto(pkg, staging)

            ffmpeg_bin = None
            ffprobe_bin = None
            for root, dirs, files in os.walk(staging):
                if "ffmpeg" in files and os.access(os.path.join(root, "ffmpeg"), os.X_OK):
                    ffmpeg_bin = Path(root) / "ffmpeg"
                if "ffprobe" in files and os.access(os.path.join(root, "ffprobe"), os.X_OK):
                    ffprobe_bin = Path(root) / "ffprobe"

            if not ffmpeg_bin or not ffprobe_bin:
                raise RuntimeError("Não encontrei ffmpeg/ffprobe extraídos.")

            target = BIN_DIR / "ffmpeg"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ffmpeg_bin, target / "ffmpeg")
            shutil.copy2(ffprobe_bin, target / "ffprobe")
            make_executable(target / "ffmpeg")
            make_executable(target / "ffprobe")

            progress("Registrando FFmpeg", 0.97, str(target))
            try_register_bins_from(target)

        else:  # macOS
            url = "https://evermeet.cx/ffmpeg/ffmpeg.zip"
            progress("Baixando FFmpeg (macOS)", 0.05, url)
            try:
                download_file(url, pkg, progress)
            except Exception as e:
                url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.zip"
                progress("Tentando fallback FFmpeg (macOS)", 0.06, url)
                download_file(url, pkg, progress)

            progress("Extraindo FFmpeg", 0.90, pkg.name)
            staging = tmpdir / "extract"
            staging.mkdir(parents=True, exist_ok=True)
            extract_archive_auto(pkg, staging)

            ffmpeg_bin = None
            ffprobe_bin = None
            for root, dirs, files in os.walk(staging):
                if "ffmpeg" in files:
                    ffmpeg_bin = Path(root) / "ffmpeg"
                if "ffprobe" in files:
                    ffprobe_bin = Path(root) / "ffprobe"
            if not ffmpeg_bin:
                raise RuntimeError("Não encontrei 'ffmpeg' no pacote para macOS.")
            target = BIN_DIR / "ffmpeg"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ffmpeg_bin, target / "ffmpeg")
            make_executable(target / "ffmpeg")
            if ffprobe_bin:
                shutil.copy2(ffprobe_bin, target / "ffprobe")
                make_executable(target / "ffprobe")

            progress("Registrando FFmpeg", 0.97, str(target))
            try_register_bins_from(target)

        progress("FFmpeg instalado", 1.0, "OK")
        return True, ""
    except Exception as e:
        msg = f"Erro FFmpeg online: {e}"
        write_log(msg)
        try:
            progress("Falha ao instalar FFmpeg", 1.0, str(e))
        except Exception:
            pass
        return False, msg

def download_and_install_mediainfo_online(progress: Callable[[str, float, str], None]) -> Tuple[bool, str]:
    """
    Baixa a versão mais recente do MediaInfo CLI para o SO/arquitetura atuais,
    a partir do índice HTML da MediaArea. Suporta:
      • Windows: MediaInfo_CLI_<ver>_Windows_x64.zip / _ARM64.zip / _i386.zip
      • Linux:   MediaInfo_CLI_<ver>_Lambda_x86_64.zip / _Lambda_arm64.zip
      • macOS:   MediaInfo_CLI_<ver>_Mac.dmg (preferido) ou *_Mac_*.zip
    """
    try:
        import tempfile, platform

        system = platform.system().lower()
        ver, url = _pick_mediainfo_url()

        tmpdir = Path(tempfile.mkdtemp(prefix="ua_mediainfo_"))
        pkg = tmpdir / f"mediainfo_{ver}"
        progress(f"Iniciando download do MediaInfo {ver}", 0.0, url)
        download_file(url, pkg, progress)

        target = BIN_DIR / "mediainfo"
        target.mkdir(parents=True, exist_ok=True)

        # Extração conforme extensão
        name = url.split("/")[-1].lower()
        progress("Extraindo MediaInfo", 0.95, name)
        if name.endswith(".zip"):
            extract_zip_to(pkg, target)
        elif name.endswith(".tar.xz") or name.endswith(".tar.gz") or name.endswith(".tar.bz2"):
            extract_tar_to(pkg, target)
        else:
            raise RuntimeError(f"Formato não suportado para extração: {name}")

        progress("Registrando MediaInfo", 0.98, str(target))
        try_register_bins_from(target)

        ok = bool(find_mediainfo_binary())
        progress("MediaInfo instalado", 1.0, "OK" if ok else "NOK")
        return ok, "" if ok else "MediaInfo não foi encontrado após a extração."
    except Exception as e:
        msg = f"Erro MediaInfo online (auto-detecção): {e}"
        write_log(msg)
        try:
            progress("Falha ao instalar MediaInfo", 1.0, str(e))
        except Exception:
            pass
        return False, msg

# ---------------------------
# Config helpers (leitura/escrita)
# ---------------------------

EXAMPLE_CONFIG_REL = Path("data") / "example-config.py"
CONFIG_REL = Path("data") / "config.py"



def ua_root_dir() -> Path:
    """Diretório onde está o upload.py dentro do bundle."""
    up = find_upload_py()
    return up.parent if up else (BUNDLE_DIR / "third_party" / "Upload-Assistant")

def ensure_ua_runtime_layout() -> Tuple[bool, str]:
    """
    Garante que o upload.py enxergue base_dir/data/config.py e base_dir/tmp/.
    Copiamos o config gerado (APP_DIR/data/config.py) para o local que o upload.py espera.
    """
    ensure_qbittorrent_config_normalized()
    try:
        root = ua_root_dir()
        data_dir = root / "data"
        tmp_dir = root / "tmp"
        data_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # fonte do config (gerado pela GUI)
        src_cfg = DATA_DIR / "config.py"
        if not src_cfg.exists():
            ok, msg = ensure_config_generated(overwrite_if_missing=False)
            if not ok:
                return False, f"Config ausente: {msg}"
        # destino que o upload.py exige
        dst_cfg = data_dir / "config.py"

        # copie se não existir ou se o src for mais novo
        copy_needed = (not dst_cfg.exists()) or (src_cfg.stat().st_mtime > dst_cfg.stat().st_mtime)
        if copy_needed:
            shutil.copy2(src_cfg, dst_cfg)

        return True, str(dst_cfg)
    except Exception as e:
        return False, f"Falha preparando layout para upload.py: {e}"


def find_example_config() -> Optional[Path]:
    p1 = BUNDLE_DIR / EXAMPLE_CONFIG_REL
    if p1.exists():
        return p1
    candidates = [
        BUNDLE_DIR / "third_party" / "Upload-Assistant" / EXAMPLE_CONFIG_REL,
        Path(__file__).resolve().parent / EXAMPLE_CONFIG_REL,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

def ensure_config_generated(overwrite_if_missing: bool = True) -> Tuple[bool, str]:
    """
    IMPORTANTE NO EXE:
      - Garante APP_DIR/data como pacote Python (cria __init__.py)
      - Copia example-config.py → APP_DIR/data/config.py se não existir
    """
    try:
        ensure_dirs()
        cfg_dir = DATA_DIR
        cfg_dir.mkdir(parents=True, exist_ok=True)

        # >>> data como pacote
        init_py = cfg_dir / "__init__.py"
        if not init_py.exists():
            init_py.write_text("", encoding="utf-8")

        cfg_dst = cfg_dir / "config.py"
        if cfg_dst.exists() and not overwrite_if_missing:
            ensure_qbittorrent_config_normalized()
            return True, "Config já existente."
        example = find_example_config()
        if not example:
            return False, "Não encontrei data/example-config.py no bundle."
        if not cfg_dst.exists():
            shutil.copy2(example, cfg_dst)
        ensure_qbittorrent_config_normalized()
        return True, f"Config disponível em: {cfg_dst}"
    except Exception as e:
        write_log(f"ensure_config_generated erro: {e}")
        return False, f"Erro ao gerar config: {e}"

def load_existing_config_dict() -> Tuple[Optional[dict], Optional[Path]]:
    ensure_dirs()
    paths = [DATA_DIR / "config.py", DATA_DIR / "config1.py"]
    for p in paths:
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8")
                m = re.search(r"config\s*=\s*({.*})", text, re.DOTALL)
                if m:
                    cfg = ast.literal_eval(m.group(1))
                    return cfg, p
            except Exception as e:
                write_log(f"Erro lendo {p}: {e}")
    return None, None

def save_config_dict(cfg: dict, existing_path: Optional[Path] = None) -> bool:
    ensure_dirs()
    out = existing_path or (DATA_DIR / "config.py")
    if out.exists():
        bak = Path(str(out) + ".bak")
        try:
            bak.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass

    def format_value(v):
        if isinstance(v, dict):
            return {k: format_value(v[k]) for k in v}
        if isinstance(v, list):
            return [format_value(x) for x in v]
        if isinstance(v, str):
            if v.lower() == "true":
                return True
            if v.lower() == "false":
                return False
            return v
        return v

    cfg_fmt = format_value(cfg)

    def write_dict(f, d, level=1):
        indent = "    " * level
        for k, v in d.items():
            f.write(f'{indent}{json.dumps(k)}: ')
            if isinstance(v, dict):
                f.write("{\n")
                write_dict(f, v, level + 1)
                f.write(f"{indent}}},\n")
            elif isinstance(v, bool):
                f.write(f"{str(v).capitalize()},\n")
            elif v is None:
                f.write("None,\n")
            else:
                f.write(f"{json.dumps(v, ensure_ascii=False)},\n")

    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write("config = {\n")
            write_dict(f, cfg_fmt, 1)
            f.write("}\n")
        return True
    except Exception as e:
        write_log(f"Erro salvando config: {e}")
        return False


def _normalize_qbittorrent_config(cfg: Dict[str, Any]) -> bool:
    """
    Ajusta a seção TORRENT_CLIENTS.qbittorrent para o formato esperado pelo Upload-Assistant.
    Força esquema qbit_url/qbit_port/qbit_user/qbit_pass/qbit_cat e torrent_client == 'qbit'.
    Retorna True se algum ajuste foi aplicado.
    """
    if not isinstance(cfg, dict):
        return False

    changed = False

    def ensure_value(container: Dict[str, Any], key: str, value: Any) -> None:
        nonlocal changed
        if container.get(key) != value:
            container[key] = value
            changed = True

    default_section = cfg.setdefault("DEFAULT", {})
    if not isinstance(default_section, dict):
        cfg["DEFAULT"] = {}
        default_section = cfg["DEFAULT"]
        changed = True

    current_default = str(default_section.get("default_torrent_client", "") or "").strip().lower()
    if current_default in {"", "qbittorrent", "qbit"}:
        if default_section.get("default_torrent_client") != "qbittorrent":
            default_section["default_torrent_client"] = "qbittorrent"
            changed = True

    signature_defaults = {
        "ua_signature_text": "Samaritano Upload-Assistant.",
        "ua_signature_link": "https://github.com/Yabai1970/SamUploadAssistantGUI",
        "ua_signature_subtext": "Ramificação do L4G's e Audionut, adicionado traduções e GUI.",
    }
    for key, value in signature_defaults.items():
        existing = default_section.get(key)
        if not isinstance(existing, str) or not existing.strip():
            ensure_value(default_section, key, value)
    if "uploader_avatar" not in default_section:
        ensure_value(default_section, "uploader_avatar", "")

    clients = cfg.setdefault("TORRENT_CLIENTS", {})
    if not isinstance(clients, dict):
        cfg["TORRENT_CLIENTS"] = {}
        clients = cfg["TORRENT_CLIENTS"]
        changed = True

    qb = clients.get("qbittorrent")
    if not isinstance(qb, dict):
        qb = {}
        clients["qbittorrent"] = qb
        changed = True

    raw_url = str(qb.get("qbit_url") or qb.get("host") or "").strip()
    if not raw_url:
        raw_url = "http://127.0.0.1"
    if not raw_url.lower().startswith(("http://", "https://")):
        raw_url = f"http://{raw_url.lstrip('/')}"
    parsed = urlparse(raw_url)
    host_clean = parsed.netloc or parsed.path or "127.0.0.1"
    host_clean = host_clean.rstrip("/\\")
    if parsed.scheme:
        normalized_url = f"{parsed.scheme}://{host_clean}"
    else:
        normalized_url = f"http://{host_clean}"

    port_raw = qb.get("qbit_port", qb.get("port", 8080))
    try:
        port_int = int(str(port_raw).strip())
    except Exception:
        port_int = 8080

    user_val = str(qb.get("qbit_user") or qb.get("username") or "admin").strip() or "admin"
    pass_val = str(qb.get("qbit_pass") or qb.get("password") or "adminadmin").strip() or "adminadmin"
    cat_val = str(qb.get("qbit_cat") or qb.get("category") or "uploads").strip() or "uploads"

    ensure_value(qb, "torrent_client", "qbit")
    ensure_value(qb, "qbit_url", normalized_url)
    ensure_value(qb, "host", host_clean)
    ensure_value(qb, "qbit_port", port_int)
    ensure_value(qb, "port", port_int)
    ensure_value(qb, "qbit_user", user_val)
    ensure_value(qb, "username", user_val)
    ensure_value(qb, "qbit_pass", pass_val)
    ensure_value(qb, "password", pass_val)
    ensure_value(qb, "qbit_cat", cat_val)
    ensure_value(qb, "category", cat_val)
    enable_search_raw = qb.get("enable_search", True)
    if isinstance(enable_search_raw, str):
        enable_search = enable_search_raw.strip().lower() not in {"false", "0", "no", "off"}
    else:
        enable_search = bool(enable_search_raw)
    allow_fallback_raw = qb.get("allow_fallback", True)
    if isinstance(allow_fallback_raw, str):
        allow_fallback = allow_fallback_raw.strip().lower() not in {"false", "0", "no", "off"}
    else:
        allow_fallback = bool(allow_fallback_raw)

    ensure_value(qb, "enable_search", enable_search)
    ensure_value(qb, "allow_fallback", allow_fallback)
    ensure_value(qb, "content_layout", qb.get("content_layout", "Original") or "Original")

    # linked_folder/local_path/remote_path devem ser listas para evitar erros posteriores
    for key in ("linked_folder", "local_path", "remote_path"):
        if key not in qb or not isinstance(qb[key], list):
            ensure_value(qb, key, [""])

    return changed


def ensure_qbittorrent_config_normalized() -> None:
    """
    Carrega config.py (se existir) e aplica normalização para qBittorrent.
    """
    try:
        cfg, path = load_existing_config_dict()
    except Exception as e:
        write_log(f"Falha lendo config para normalização: {e}")
        return
    if not path:
        return
    if not isinstance(cfg, dict):
        try:
            namespace = runpy.run_path(str(path))
            cfg = namespace.get("config")
        except Exception as e:
            write_log(f"Falha executando config para normalização: {e}")
            return
    if not isinstance(cfg, dict):
        return
    if _normalize_qbittorrent_config(cfg):
        ok = save_config_dict(cfg, path)
        if ok:
            write_log("Configuração qBittorrent normalizada automaticamente.")
        else:
            write_log("Falha ao salvar config após normalização do qBittorrent.")


def _ensure_std_streams():
    """
    Garante sys.stdout/err/in e sys.__stdout__/__stderr__/__stdin__ mesmo sem console.
    Não esconde erros: só evita NoneType.
    """
    def _ensure(name: str, factory: Callable[[], io.TextIOBase]):
        cur = getattr(sys, name, None)
        if cur is None:
            cur = factory()
            setattr(sys, name, cur)
        dunder = f"__{name}__"
        if getattr(sys, dunder, None) is None:
            setattr(sys, dunder, cur)

    _ensure("stdin",  lambda: NullStream())
    _ensure("stdout", lambda: NullStream())
    _ensure("stderr", lambda: NullStream())


# ---------------------------


def ensure_upload_assistant_workspace() -> Optional[Path]:
    ensure_dirs()
    src_bundle = BUNDLE_DIR / "third_party" / "Upload-Assistant"
    dst_local = APP_DIR / "third_party" / "Upload-Assistant"
    try:
        if running_frozen() and src_bundle.exists():
            dst_local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_bundle, dst_local, dirs_exist_ok=True)
    except Exception as e:
        write_log(f"Erro ao preparar workspace do Upload-Assistant: {e}")
    candidates = [
        dst_local,
        src_bundle,
        Path(__file__).resolve().parent / "third_party" / "Upload-Assistant",
        BUNDLE_DIR / "Upload-Assistant",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None

# Execução do Upload-Assistant (upload.py)
# ---------------------------

def find_upload_py() -> Optional[Path]:
    root = ensure_upload_assistant_workspace()
    if root:
        candidate = root / "upload.py"
        if candidate.exists():
            return candidate
    candidates = [
        BUNDLE_DIR / "upload.py",
        BUNDLE_DIR / "third_party" / "Upload-Assistant" / "upload.py",
        Path(__file__).resolve().parent / "upload.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

class Tee(io.TextIOBase):
    encoding = "utf-8"

    def __init__(self, *streams: io.TextIOBase, callbacks: Optional[Sequence[Callable[[str], None]]] = None):
        super().__init__()
        self._streams = [st for st in streams if st is not None]
        self._callbacks = list(callbacks or [])

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        if s is None:
            return 0
        for st in self._streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass
        for cb in self._callbacks:
            try:
                cb(s)
            except Exception:
                pass
        return len(s)

    def flush(self) -> None:
        for st in self._streams:
            try:
                st.flush()
            except Exception:
                pass



class NullStream(io.TextIOBase):
    encoding = "utf-8"

    def write(self, s: str) -> int:
        return len(s or "")

    def read(self, _size: int = -1) -> str:
        return ""

    def readline(self, _size: int = -1) -> str:
        return ""

    def flush(self) -> None:
        pass

    @property
    def closed(self) -> bool:  # type: ignore[override]
        return False

    def close(self) -> None:  # type: ignore[override]
        pass

    def isatty(self) -> bool:  # type: ignore[override]
        return False


PROMPT_TRANSLATION_REGEX = [
    (
        re.compile(r"do you want to use these ids from (?P<source>.+?)\?\s*(?:\(y/n\):?)?", re.IGNORECASE),
        lambda m: f"Deseja usar esses IDs de {m.group('source')}?",
    ),
    (re.compile(r"do you want to use these ids\??", re.IGNORECASE), lambda m: "Deseja usar esses IDs?"),
    (re.compile(r"do you want to upload anyway\??", re.IGNORECASE), lambda m: "Deseja fazer o upload mesmo assim?"),
    (
        re.compile(r"upload to (?P<tracker>.+?) anyway\??", re.IGNORECASE),
        lambda m: f"Deseja enviar para {m.group('tracker')} mesmo assim?",
    ),
    (
        re.compile(r"upload to (?P<tracker>.+?) with the name (?P<name>.+?)\??", re.IGNORECASE),
        lambda m: f"Enviar para {m.group('tracker')} com o nome {m.group('name')}?",
    ),
    (
        re.compile(r"do you want to use this release\?\s*(?:\(y/n\):?)?", re.IGNORECASE),
        lambda m: "Deseja usar este lançamento?",
    ),
    (
        re.compile(r"remove '([^']+)' from audio languages\??", re.IGNORECASE),
        lambda m: f"Remover '{m.group(1)}' das línguas de áudio?",
    ),
    (
        re.compile(r"found conformance errors in mediainfo.*proceed to upload anyway\??", re.IGNORECASE),
        lambda m: "Foram encontrados erros de conformidade na MediaInfo. Deseja continuar com o upload mesmo assim?",
    ),
    (
        re.compile(r"please enter tmdb id in this format: tv/12345 or movie/12345", re.IGNORECASE),
        lambda m: "Informe o TMDb ID neste formato: tv/12345 ou movie/12345.",
    ),
    (
        re.compile(r"enter comparison index number", re.IGNORECASE),
        lambda m: "Informe o número do índice de comparação:",
    ),
    (
        re.compile(r"enter the number of the correct entry, 0 for none, or manual imdb id", re.IGNORECASE),
        lambda m: "Informe o número da entrada correta, 0 para nenhuma, ou insira manualmente o IMDb ID (tt1234567):",
    ),
    (
        re.compile(r"enter the number of the correct show \(1-(?P<max>\d+)\) or 0 to skip:", re.IGNORECASE),
        lambda m: f"Informe o número do show correto (1-{m.group('max')}) ou 0 para pular:",
    ),
    (
        re.compile(r"selection \(1-(?P<max>\d+)/a/n\):", re.IGNORECASE),
        lambda m: f"Seleção (1-{m.group('max')}/a/n):",
    ),
    (
        re.compile(r"enter the release number \(1-(?P<max>\d+)\) to print logs:", re.IGNORECASE),
        lambda m: f"Informe o número do lançamento (1-{m.group('max')}) para exibir os logs:",
    ),
    (
        re.compile(r"enter a new edition title for playlist (?P<name>.+?) \(or press enter to keep the current label\):", re.IGNORECASE),
        lambda m: f"Informe um novo título de edição para a playlist {m.group('name')} (ou pressione Enter para manter o rótulo atual):",
    ),
    (
        re.compile(r"no results found\. please enter a manual imdb id", re.IGNORECASE),
        lambda m: "Nenhum resultado encontrado. Informe manualmente o IMDb ID (tt1234567) ou 0 para pular:",
    ),
    (
        re.compile(r"unable to find imdb id, please enter e\.g\.\(tt1234567\) or press enter to skip uploading to (?P<tracker>.+?):", re.IGNORECASE),
        lambda m: f"Não foi possível encontrar o IMDb ID; informe ex. (tt1234567) ou pressione Enter para pular o envio para {m.group('tracker')}:",
    ),
    (
        re.compile(r"log in again and create new session\??", re.IGNORECASE),
        lambda m: "Entrar novamente e criar uma nova sessão?",
    ),
    (re.compile(r"mark trumpable\??", re.IGNORECASE), lambda m: "Marcar como trumpável?"),
    (
        re.compile(r"is this a derived layer release\??", re.IGNORECASE),
        lambda m: "Este é um lançamento de camada derivada?",
    ),
    (
        re.compile(r"send to takeupload\.php\??", re.IGNORECASE),
        lambda m: "Enviar para takeupload.php?",
    ),
    (re.compile(r"select the proper type", re.IGNORECASE), lambda m: "Selecione o tipo correto."),
    (
        re.compile(r"please select any/all applicable options", re.IGNORECASE),
        lambda m: "Selecione todas as opções aplicáveis:",
    ),
    (
        re.compile(r"select edition number \(1-(?P<max>\d+)\) or press enter to use the closest match:", re.IGNORECASE),
        lambda m: f"Selecione o número da edição (1-{m.group('max')}) ou pressione Enter para usar a mais próxima:",
    ),
    (
        re.compile(r"select edition number \(1-(?P<max>\d+)\), press e to use playlist edition or press enter to use the closest match:", re.IGNORECASE),
        lambda m: f"Selecione o número da edição (1-{m.group('max')}), pressione 'e' para usar a edição da playlist ou Enter para usar a mais próxima:",
    ),
    (
        re.compile(r"show \(a\)ll remaining (?P<count>\d+) files, \(c\)ontinue with incomplete pack, or \(q\)uit\? \(a/c/Q\):", re.IGNORECASE),
        lambda m: f"Mostrar (a) todos os {m.group('count')} arquivos restantes, (c) continuar com o pacote incompleto ou (q) sair? (a/c/Q):",
    ),
    (
        re.compile(r"show \(n\)ext (?P<count>\d+) files, \(a\)ll remaining files, \(c\)ontinue with incomplete pack, or \(q\)uit\? \(n/a/c/Q\):", re.IGNORECASE),
        lambda m: f"Mostrar (n) os próximos {m.group('count')} arquivos, (a) todos os arquivos restantes, (c) continuar com o pacote incompleto ou (q) sair? (n/a/c/Q):",
    ),
    (
        re.compile(r"input args that need correction", re.IGNORECASE),
        lambda m: "Informe os argumentos que precisam de correção (ex.: --tag NTb --category tv --tmdb 12345):",
    ),
]

PROMPT_TRANSLATION_REPLACEMENTS = [
    (r"\bDo you want to\b", "Você deseja"),
    (r"\bDo you want\b", "Você quer"),
    (r"\bPlease enter\b", "Informe"),
    (r"\bPlease\b", "Por favor"),
    (r"\bEnter\b", "Digite"),
    (r"\bSelect\b", "Selecione"),
    (r"\bcomparison\b", "comparação"),
    (r"\bProceed\b", "Prosseguir"),
]


def _strip_rich_markup(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\[/?[a-zA-Z0-9_ ]+\]", "", text)


def normalize_prompt_text(message: str) -> str:
    base = _strip_rich_markup(message)
    base = re.sub(r"\s+", " ", base).strip()
    return base.lower()


PROMPT_TRANSLATION_MAP = {
    "--keep-folder was specified. using complete folder for torrent creation.": "--keep-folder foi especificado. Usando a pasta completa para criar o torrent.",
    "2fa required: please enter 2fa code": "2FA obrigatório: informe o código 2FA.",
    "all releases selected": "Todos os lançamentos selecionados.",
    "continue with incomplete season pack? (y/n):": "Continuar com o pacote de temporada incompleto?",
    "correct?": "Correto?",
    "do you want to remove it?": "Deseja remover?",
    "do you want to upload anyway?": "Deseja enviar mesmo assim?",
    "do you want to upload with this file?": "Deseja enviar com este arquivo?",
    "do you want to use this release? (y/n):": "Deseja usar este lançamento?",
    "enter 'd' to discard, or press enter to keep it as is:": "Digite 'd' para descartar ou pressione Enter para manter como está:",
    "enter 'e' to edit, 'd' to discard, or press enter to keep it as is:": "Digite 'e' para editar, 'd' para descartar ou pressione Enter para manter como está:",
    "enter 'e' to edit, or press enter to keep it as is:": "Digite 'e' para editar ou pressione Enter para manter como está:",
    "enter 'e' to edit, or press enter to save as is:": "Digite 'e' para editar ou pressione Enter para salvar como está:",
    "enter 'u' to update, 'a' to add specific new files, 'e' to edit, 'd' to discard, or press enter to keep it as is:": "Digite 'u' para atualizar, 'a' para adicionar arquivos específicos, 'e' para editar, 'd' para descartar ou pressione Enter para manter como está:",
    "enter 'y' to upload, or press enter to skip uploading:": "Digite 'y' para enviar ou pressione Enter para pular o upload:",
    "enter comparison index number:": "Informe o número do índice de comparação:",
    "enter language code for hc subtitle languages": "Informe o código de idioma das legendas hardcoded:",
    "enter numbers (e.g., 1,3,5):": "Informe os números (ex.: 1,3,5):",
    "enter the number of the playlist you want to select:": "Informe o número da playlist que deseja selecionar:",
    "get files for manual upload?": "Obter arquivos para upload manual?",
    "invalid imdb id format. expected format: tt1234567": "Formato de IMDb ID inválido. O formato esperado é tt1234567.",
    "no poster was found. please input a link to a poster:": "Nenhum pôster foi encontrado. Informe um link para um pôster:",
    "no release selected.": "Nenhum lançamento selecionado.",
    "no results found. please enter a manual imdb id (tt1234567) or 0 to skip:": "Nenhum resultado encontrado. Informe manualmente o IMDb ID (tt1234567) ou 0 para pular:",
    "no english subs and english audio is not the first audio track, should this be trumpable?": "Sem legendas em inglês e o áudio em inglês não é a primeira faixa. Marcar como trumpável?",
    "no english subs and no audio tracks found should this be trumpable?": "Sem legendas em inglês e nenhuma faixa de áudio encontrada. Marcar como trumpável?",
    "or push enter to try a different search:": "Ou pressione Enter para tentar uma busca diferente:",
    "please enter new name:": "Informe o novo nome:",
    "please enter tmdb id (format: tv/12345 or movie/12345):": "Informe o TMDb ID (formato: tv/12345 ou movie/12345):",
    "please enter tmdb id in this format: tv/12345 or movie/12345": "Informe o TMDb ID neste formato: tv/12345 ou movie/12345.",
    "please enter a proper name": "Informe um nome válido.",
    "please enter at least one tag. comma separated (action, animation, short):": "Informe pelo menos uma tag, separadas por vírgula (ex.: action, animation, short):",
    "please select any/all applicable options:": "Selecione todas as opções aplicáveis:",
    "processing complete": "Processamento concluído.",
    "region required; skipping shri.": "Região obrigatória; ignorando SHRI.",
    "shri: distributor (optional, enter to skip):": "SHRI: Distribuidora (opcional, pressione Enter para pular):",
    "shri: region code not found for disc. please enter it manually (mandatory):": "SHRI: Código de região não encontrado para o disco. Informe manualmente (obrigatório):",
    "select playlists:": "Selecione as playlists:",
    "select the correct movie:": "Selecione o filme correto:",
    "select the proper type": "Selecione o tipo correto.",
    "selection:": "Seleção:",
    "skipped - not using blu-ray.com information": "Ignorado - não usar informações do Blu-ray.com.",
    "unable to find youtube trailer, please link one e.g.(https://www.youtube.com/watch?v=dqw4w9wgxcq)": "Não foi possível encontrar trailer no YouTube. Informe um link (ex.: https://www.youtube.com/watch?v=dQw4w9WgXcQ).",
    "warning: mandarin subtitle or audio not found. do you want to continue with the upload anyway? (y/n):": "Aviso: áudio ou legenda em mandarim não encontrados. Deseja continuar com o upload mesmo assim?",
    "what language/s are the hardcoded subtitles?": "Quais são os idiomas das legendas hardcoded?",
    "for all audio tracks, eg: english, spanish:": "Para todas as faixas de áudio, ex.: inglês, espanhol:",
    "for all subtitle tracks, eg: english, spanish:": "Para todas as faixas de legenda, ex.: inglês, espanhol:",
    "you specified --keep-folder. uploading in folders might not be allowed. proceed? y/n:": "Você especificou --keep-folder. Upload em pastas pode não ser permitido. Prosseguir?",
    "please enter douban link:": "Informe o link do Douban:",
    "mtv 2fa code:": "Código 2FA do MTV:",
    "ttg 2fa code:": "Código 2FA do TTG:",
    "está correto? y/n:": "Está correto? Mande Y para Sim ou N para Não",
}


def translate_prompt_pt(message: str) -> str:
    return (message or "").strip()


CANCELLED_PROMPT = object()

YES_NO_PATTERNS = [
    re.compile(r"([Yy])\s*/\s*([Nn])"),
    re.compile(r"([Nn])\s*/\s*([Yy])"),
    re.compile(r"([Ss])\s*/\s*([Nn])"),
    re.compile(r"([Nn])\s*/\s*([Ss])"),
]


def detect_yes_no_prompt(message: str) -> Tuple[bool, Optional[bool]]:
    msg = (message or "").strip()
    if not msg:
        return False, None
    for pattern in YES_NO_PATTERNS:
        match = pattern.search(msg)
        if match:
            first, second = match.groups()
            first_lower = first.lower()
            second_lower = second.lower()
            default: Optional[bool] = None
            if first.isupper() and not second.isupper():
                default = first_lower in ("y", "s")
            elif second.isupper() and not first.isupper():
                default = second_lower in ("y", "s")
            elif first.isupper() and second.isupper():
                # Both highlighted; fall back to yes as default.
                default = first_lower in ("y", "s")
            return True, default
    lower_msg = msg.lower()
    if lower_msg.endswith((" (y/n)", " (s/n)", " y/n", " s/n", " y/n:", " s/n:", " y/n?", " s/n?")):
        return True, None
    return False, None


class PromptBridge:
    """
    Faz a ponte entre as perguntas interativas do Upload Assistant e a interface gráfica.
    """

    def __init__(self, handler: Optional[Callable[..., Any]]):
        self.handler = handler
        self._original_input = None  # type: ignore[assignment]
        self._cli_ui = None
        self._cli_originals: Dict[str, Any] = {}
        self._installed = False

    def install(self) -> None:
        if not self.handler:
            return
        import builtins

        self._original_input = builtins.input
        builtins.input = self._input_wrapper  # type: ignore[assignment]
        try:
            self._cli_ui = importlib.import_module("cli_ui")
        except Exception:
            self._cli_ui = None

        if self._cli_ui:
            names = ["ask_string", "ask_yes_no", "ask_choice", "select_choices", "ask_password"]
            for name in names:
                if hasattr(self._cli_ui, name):
                    self._cli_originals[name] = getattr(self._cli_ui, name)
            if hasattr(self._cli_ui, "input"):
                self._cli_originals["input_attr"] = getattr(self._cli_ui, "input")

            if "ask_string" in self._cli_originals:
                self._cli_ui.ask_string = self._ask_string  # type: ignore[attr-defined]
            if "ask_yes_no" in self._cli_originals:
                self._cli_ui.ask_yes_no = self._ask_yes_no  # type: ignore[attr-defined]
            if "ask_choice" in self._cli_originals:
                self._cli_ui.ask_choice = self._ask_choice  # type: ignore[attr-defined]
            if "select_choices" in self._cli_originals:
                self._cli_ui.select_choices = self._select_choices  # type: ignore[attr-defined]
            if "ask_password" in self._cli_originals:
                self._cli_ui.ask_password = self._ask_password  # type: ignore[attr-defined]
            self._cli_ui.input = self._cli_input  # type: ignore[attr-defined]

        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        import builtins

        if self._original_input is not None:
            builtins.input = self._original_input  # type: ignore[assignment]
        if self._cli_ui:
            for name, func in self._cli_originals.items():
                if name == "input_attr":
                    setattr(self._cli_ui, "input", func)
                else:
                    setattr(self._cli_ui, name, func)
        self._cli_originals.clear()
        self._cli_ui = None
        self._installed = False

    # --- Helpers ---------------------------------------------------------

    def _render_tokens(self, tokens: Sequence[Any]) -> str:
        if not tokens:
            return ""
        if self._cli_ui and hasattr(self._cli_ui, "process_tokens"):
            try:
                _, plain = self._cli_ui.process_tokens(tokens, end="", sep=" ")
                plain = plain.strip()
                if plain.startswith("::"):
                    plain = plain[2:].lstrip()
                return plain
            except Exception:
                pass
        parts: List[str] = []
        for tok in tokens:
            parts.append(str(tok))
        return " ".join(parts).strip()

    def _compose_message(self, raw_tokens: Sequence[Any]) -> str:
        tokens = list(raw_tokens)
        if self._cli_ui and hasattr(self._cli_ui, "get_ask_tokens"):
            try:
                tokens = self._cli_ui.get_ask_tokens(tokens)  # type: ignore[attr-defined]
            except Exception:
                pass
        return self._render_tokens(tokens)

    def _call_handler(self, prompt_type: str, message: str, **kwargs: Any) -> Any:
        if not self.handler:
            return None
        return self.handler(prompt_type, message, **kwargs)

    # --- Wrappers --------------------------------------------------------

    def _ask_string(self, *question: Any, default: Optional[str] = None) -> Optional[str]:
        message = self._compose_message(question)
        response = self._call_handler("text", message, default=default, is_password=False)
        if response is None or response == "":
            return default
        return str(response)

    def _ask_password(self, *question: Any) -> str:
        message = self._compose_message(question)
        response = self._call_handler("text", message, default="", is_password=True)
        if response is None:
            return ""
        return str(response)

    def _ask_yes_no(self, *question: Any, default: bool = False) -> bool:
        message = self._compose_message(question)
        result = self._call_handler("yes_no", message, default=default)
        if result is None:
            return default
        return bool(result)

    def _ask_choice(
        self,
        *prompt: Any,
        choices: List[Any],
        func_desc: Optional[Callable[[Any], str]] = None,
        sort: Optional[bool] = True,
    ) -> Any:
        descriptor = func_desc or (lambda x: str(x))
        working = list(choices)
        if sort:
            working.sort(key=descriptor)
            try:
                choices[:] = working
            except Exception:
                pass
        options = []
        for idx, choice in enumerate(working, start=1):
            label = descriptor(choice)
            options.append({"label": f"{idx}. {label}", "value": choice})
        message = self._compose_message(prompt)
        selected = self._call_handler("choice", message, options=options)
        return selected

    def _select_choices(
        self,
        *prompt: Any,
        choices: List[Any],
        func_desc: Optional[Callable[[Any], str]] = None,
        sort: Optional[bool] = True,
    ) -> Any:
        descriptor = func_desc or (lambda x: str(x))
        working = list(choices)
        if sort:
            working.sort(key=descriptor)
            try:
                choices[:] = working
            except Exception:
                pass
        options = []
        for idx, choice in enumerate(working, start=1):
            label = descriptor(choice)
            options.append({"label": f"{idx}. {label}", "value": choice})
        message = self._compose_message(prompt)
        selected = self._call_handler("multi_choice", message, options=options)
        if selected is None:
            return None
        return selected

    def _cli_input(self, *question: Any) -> str:
        message = self._compose_message(question)
        response = self._call_handler("text", message, default="", is_password=False)
        if response is None:
            return ""
        return str(response)

    def _input_wrapper(self, prompt: str = "") -> str:
        response = self._call_handler("text", prompt or "", default="", is_password=False)
        if response is None:
            return ""
        return str(response)

def run_upload_assistant(
    args: List[str],
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    on_stdout: Optional[Callable[[str], None]] = None,
    on_stderr: Optional[Callable[[str], None]] = None,
    prompt_handler: Optional[Callable[..., Any]] = None,
) -> Tuple[int, str, str]:
    """
    Executa o upload.py do Upload-Assistant dentro do mesmo processo.
    Ajustes importantes para PyInstaller:
      - APP_DIR/data como pacote (feito em ensure_config_generated)
      - sys.path: APP_DIR em 1º, UA root em 2º (para data.config e src/*)
      - fallback alias bencode → bencode.py se necessário
    """
    _ensure_std_streams()

    _ensure_std_streams()

    up = find_upload_py()
    if up is None:
        write_log("upload.py nao encontrado no bundle.")
        return 2, "", ""
    if cwd is None:
        cwd = APP_DIR

    ua_root = up.parent  # third_party/Upload-Assistant

    # Prepara argv
    old_argv = sys.argv[:]
    sys.argv = [str(up)] + args

    buf_out, buf_err = io.StringIO(), io.StringIO()
    original_stdout, original_stderr, original_stdin = sys.stdout, sys.stderr, sys.stdin
    stdout_base = original_stdout if original_stdout is not None else NullStream()
    stderr_base = original_stderr if original_stderr is not None else NullStream()
    stdin_base = original_stdin if original_stdin is not None else NullStream()
    logf = open(log_path("upload_assistant.log"), "a", encoding="utf-8")
    try:
        faulthandler.enable(logf)
    except Exception:
        pass
    old_env = os.environ.copy()
    old_sys_path = sys.path[:]
    original_dunder_stdout = getattr(sys, "__stdout__", None)
    original_dunder_stderr = getattr(sys, "__stderr__", None)
    original_dunder_stdin = getattr(sys, "__stdin__", None)
    prompt_bridge: Optional[PromptBridge] = None
    try:
        # --- PATH de import: APP_DIR primeiro (para data.config),
        # depois o root do UA (para src/, cogs/, etc.)
        if str(APP_DIR) in sys.path:
            sys.path.remove(str(APP_DIR))
        if str(ua_root) in sys.path:
            sys.path.remove(str(ua_root))
        sys.path.insert(0, str(APP_DIR))
        sys.path.insert(1, str(ua_root))

        # Fallback: mapear 'bencode' → 'bencode.py' se preciso
        try:
            import bencode  # noqa: F401
        except ModuleNotFoundError:
            try:
                import bencodepy as _b

                sys.modules["bencode"] = _b
            except Exception:
                pass

        if env:
            os.environ.update(env)
        old_cwd = os.getcwd()
        os.chdir(str(cwd))

        stdout_callbacks: List[Callable[[str], None]] = []
        stderr_callbacks: List[Callable[[str], None]] = []
        if on_stdout:
            stdout_callbacks.append(on_stdout)
        if on_stderr:
            stderr_callbacks.append(on_stderr)

        if prompt_handler:
            prompt_bridge = PromptBridge(prompt_handler)
            try:
                prompt_bridge.install()
            except Exception:
                prompt_bridge = None

        sys.stdin = stdin_base
        sys.__stdin__ = stdin_base  # type: ignore[attr-defined]
        tee_stdout = Tee(stdout_base, logf, buf_out, callbacks=stdout_callbacks)
        tee_stderr = Tee(stderr_base, logf, buf_err, callbacks=stderr_callbacks)
        sys.stdout = tee_stdout
        sys.stderr = tee_stderr
        sys.__stdout__ = tee_stdout  # type: ignore[attr-defined]
        sys.__stderr__ = tee_stderr  # type: ignore[attr-defined]
        runpy.run_path(str(up), run_name="__main__")
        rc = 0
    except SystemExit as se:
        rc = int(se.code) if isinstance(se.code, int) else (0 if se.code is None else 1)
    except KeyboardInterrupt:
        message = 'Upload cancelado pelo usuario.'
        buf_err.write(message + '\n')
        for cb in stderr_callbacks:
            try:
                cb(message + '\n')
            except Exception:
                pass
        rc = 130
    except Exception:
        traceback.print_exc()
        rc = 1
    finally:
        if prompt_bridge:
            try:
                prompt_bridge.uninstall()
            except Exception:
                pass
        sys.stdin = original_stdin
        sys.__stdin__ = original_dunder_stdin  # type: ignore[attr-defined]
        sys.stdout = original_stdout
        sys.__stdout__ = original_dunder_stdout  # type: ignore[attr-defined]
        sys.stderr = original_stderr
        sys.__stderr__ = original_dunder_stderr  # type: ignore[attr-defined]
        sys.argv = old_argv
        os.environ.clear()
        os.environ.update(old_env)
        sys.path = old_sys_path
        try:
            os.chdir(old_cwd)
        except Exception:
            pass
        try:
            logf.close()
        except Exception:
            pass

    stdout_text = buf_out.getvalue()
    stderr_text = buf_err.getvalue()
    (LOG_DIR / "last_stdout.log").write_text(stdout_text, encoding="utf-8")
    (LOG_DIR / "last_stderr.log").write_text(stderr_text, encoding="utf-8")
    return rc, stdout_text, stderr_text

# ---------------------------
# PROGRESS DIALOG (modal)
# ---------------------------

if USE_CTK:
    class ProgressDialog(ctk.CTkToplevel):
        def __init__(self, master, title="Instalando dependências..."):
            super().__init__(master)
            self.title(title)
            self.geometry("520x160")
            self.transient(master); self.grab_set()
            self.resizable(False, False)
            self.label = ctk.CTkLabel(self, text="Iniciando...")
            self.label.pack(padx=12, pady=(12,6), anchor="w")
            self.extra = ctk.CTkLabel(self, text="", font=("TkDefaultFont", 10))
            self.extra.pack(padx=12, pady=(0,6), anchor="w")
            self.pb = ctk.CTkProgressBar(self)
            self.pb.pack(fill="x", padx=12, pady=(0,12))
            self.pb.set(0.0)
            self.btn_close = ctk.CTkButton(self, text="Fechar", state="disabled", command=self.destroy)
            self.btn_close.pack(pady=(0,10))
            self.protocol("WM_DELETE_WINDOW", lambda: None)  # não fechar no meio

        def update_progress(self, msg: str, ratio: float, extra: str):
            self.label.configure(text=msg)
            self.extra.configure(text=extra or "")
            ratio = min(max(ratio, 0.0), 1.0)
            self.pb.set(ratio)
            self.update_idletasks()

        def done(self, error: Optional[str]=None):
            if error:
                self.label.configure(text=f"Concluído com erro")
                self.extra.configure(text=error)
            else:
                self.label.configure(text=f"Concluído")
            self.pb.set(1.0)
            self.btn_close.configure(state="normal")
            self.update_idletasks()
else:
    import tkinter as tk
    from tkinter import ttk
    class ProgressDialog(ctk.Toplevel):  # type: ignore
        def __init__(self, master, title="Instalando dependências..."):
            super().__init__(master)
            self.title(title)
            self.geometry("520x160")
            self.transient(master); self.grab_set()
            self.resizable(False, False)
            frm = tk.Frame(self); frm.pack(fill="both", expand=True, padx=10, pady=10)
            self.label = tk.Label(frm, text="Iniciando..."); self.label.pack(anchor="w")
            self.extra = tk.Label(frm, text="", font=("TkDefaultFont", 9)); self.extra.pack(anchor="w", pady=(2,6))
            self.pb = ttk.Progressbar(frm, orient="horizontal", mode="determinate", length=480)
            self.pb.pack(fill="x")
            self.pb["value"] = 0
            self.btn_close = tk.Button(frm, text="Fechar", state="disabled", command=self.destroy)
            self.btn_close.pack(pady=(10,0))
            self.protocol("WM_DELETE_WINDOW", lambda: None)

        def update_progress(self, msg: str, ratio: float, extra: str):
            self.label.configure(text=msg); self.extra.configure(text=extra or "")
            ratio = min(max(ratio, 0.0), 1.0)
            self.pb["value"] = ratio * 100.0
            self.update_idletasks()

        def done(self, error: Optional[str]=None):
            if error:
                self.label.configure(text=f"Concluído com erro")
                self.extra.configure(text=error)
            else:
                self.label.configure(text=f"Concluído")
            self.pb["value"] = 100.0
            self.btn_close.configure(state="normal")
            self.update_idletasks()

# ---------------------------
# GUI principal + Assistente de Configuração
# ---------------------------



class UploadRunner:
    def __init__(self, app: "App"):
        self.app = app
        self.thread: Optional[threading.Thread] = None

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, args: List[str]) -> None:
        if self.is_running():
            raise RuntimeError("Upload já em execução")
        self.thread = threading.Thread(target=self._worker, args=(args,), daemon=True)
        self.thread.start()

    def _worker(self, args: List[str]) -> None:
        self.app.call_in_main_thread(self.app.on_upload_started)
        rc = 1
        stdout_text = ""
        stderr_text = ""
        error: Optional[Exception] = None
        try:
            rc, stdout_text, stderr_text = run_upload_assistant(
                args,
                cwd=APP_DIR,
                env=build_env_with_bins(),
                on_stdout=self._handle_stdout,
                on_stderr=self._handle_stderr,
                prompt_handler=self._handle_prompt,
            )
        except Exception as exc:
            error = exc
            stderr_text = "".join(traceback.format_exception(exc))
            self._handle_stderr(stderr_text)
            rc = 1
        self.app.call_in_main_thread(self.app.on_upload_finished, rc, stdout_text, stderr_text, error)

    def _handle_stdout(self, chunk: str) -> None:
        self.app.call_in_main_thread(self.app.on_upload_output, chunk, "stdout")

    def _handle_stderr(self, chunk: str) -> None:
        self.app.call_in_main_thread(self.app.on_upload_output, chunk, "stderr")

    def _handle_prompt(self, prompt_type: str, message: str, **extra: Any) -> Any:
        event = threading.Event()
        result: Dict[str, Any] = {}

        def resolver(value: Any) -> None:
            result["value"] = value
            event.set()

        self.app.request_prompt(prompt_type, message, resolver, **extra)
        event.wait()
        value = result.get("value")
        if value is CANCELLED_PROMPT:
            raise KeyboardInterrupt()
        return value

class App(ctk.CTk if USE_CTK else ctk.Tk):  # type: ignore[misc]
    def __init__(self) -> None:
        if USE_CTK:
            super().__init__()
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("dark-blue")
        else:
            super().__init__()  # type: ignore[misc]

        self.title("Upload Assistant")
        self.geometry("980x700")
        ensure_dirs()
        ensure_config_generated(overwrite_if_missing=False)
        ensure_qbittorrent_config_normalized()

        # LOGO
        self.logo_label = None
        self.logo_ref = None
        self.draw_logo()

        # Conteúdo
        self.create_widgets()
        self.upload_runner: Optional["UploadRunner"] = None
        self.current_prompt_state: Optional[Dict[str, Any]] = None
        self.prompt_entry_var = None
        self.prompt_choice_var = None
        self.prompt_option_vars: List[Any] = []
        self.prompt_context_lines: Deque[str] = deque(maxlen=8)
        self.prompt_context_partial = ""
        self._active_prompt_bindings: List[str] = []

        # Sempre fullscreen
        self.force_fullscreen()

        self.ffmpeg_ok = False
        self.mediainfo_ok = False

        # Checagem automática (com popup e progresso)
        self.startup_check()

    # --- Fullscreen helpers

    def force_fullscreen(self) -> None:
        try:
            if os.name == "nt":
                self.state("zoomed")
            else:
                try:
                    self.attributes("-zoomed", True)
                except Exception:
                    self.attributes("-fullscreen", True)
        except Exception:
            try:
                self.attributes("-fullscreen", True)
            except Exception:
                pass

    # --- Logo

    def find_logo_path(self) -> Optional[Path]:
        p1 = RES_DIR / "logo.png"
        if p1.exists():
            return p1
        p2 = BUNDLE_DIR / "logo.png"
        if p2.exists():
            return p2
        return None

    def draw_logo(self) -> None:
        lp = self.find_logo_path()
        if not lp:
            return
        if USE_CTK:
            top = ctk.CTkFrame(self)
        else:
            top = ctk.Frame(self)
        top.pack(side="top", fill="x", padx=10, pady=(10, 4))

        desired_h = 80
        try:
            if USE_CTK and PIL_OK:
                img = Image.open(lp)
                w, h = img.size
                new_w = max(1, int(w * (desired_h / float(h))))
                img = img.resize((new_w, desired_h), Image.LANCZOS)
                from customtkinter import CTkImage
                cimg = CTkImage(light_image=img, dark_image=img, size=(new_w, desired_h))
                lbl = ctk.CTkLabel(top, image=cimg, text="")
                lbl.pack(side="top", pady=2)
                self.logo_label = lbl
                self.logo_ref = cimg
            else:
                import tkinter as tk
                pimg = tk.PhotoImage(file=str(lp))
                lbl = tk.Label(top, image=pimg)
                lbl.image = pimg
                lbl.pack(side="top", pady=2)
                self.logo_label = lbl
                self.logo_ref = pimg
        except Exception as e:
            write_log(f"Falha ao desenhar logo: {e}")

    def create_widgets(self) -> None:
        if USE_CTK: top = ctk.CTkFrame(self)
        else:       top = ctk.Frame(self)
        top.pack(side="top", fill="x", padx=10, pady=10)

        self.btn_check  = self._btn(top, text="Verificar dependências", command=self.on_check_deps);   self.btn_check.pack(side="left", padx=5)
        self.btn_install= self._btn(top, text="Instalar dependências",  command=self.on_install_deps); self.btn_install.pack(side="left", padx=5)
        self.btn_wizard = self._btn(top, text="Assistente de Configuração", command=self.on_open_wizard); self.btn_wizard.pack(side="left", padx=5)
        self.btn_edit_cfg = self._btn(top, text="Editar config.py", command=self.on_edit_config); self.btn_edit_cfg.pack(side="left", padx=5)
        self.btn_run    = self._btn(top, text="Iniciar upload",         command=self.on_run);          self.btn_run.pack(side="left", padx=5)
        self.btn_logs   = self._btn(top, text="Abrir logs",             command=self.on_open_logs);    self.btn_logs.pack(side="left", padx=5)

        # Status
        if USE_CTK: status = ctk.CTkFrame(self)
        else:       status = ctk.Frame(self)
        status.pack(side="top", fill="x", padx=10, pady=(0,10))
        self.lbl_ffmpeg   = self._label(status, "FFmpeg: ...");     self.lbl_ffmpeg.pack(side="left", padx=10)
        self.lbl_mediainfo= self._label(status, "MediaInfo: ...");  self.lbl_mediainfo.pack(side="left", padx=10)
        self.lbl_config   = self._label(status, f"Config: {DATA_DIR / 'config.py'}"); self.lbl_config.pack(side="left", padx=10)

        # Parâmetros básicos
        if USE_CTK: params = ctk.CTkFrame(self)
        else:       params = ctk.Frame(self)
        params.pack(side="top", fill="x", padx=10, pady=(0,10))
        self._label(params, "Caminho da mídia (arquivo/pasta):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.var_path = ctk.StringVar(value=""); self.ent_path = self._entry(params, textvariable=self.var_path)
        self.ent_path.grid(row=0, column=1, sticky="ew", padx=5, pady=5); params.grid_columnconfigure(1, weight=1)
        self._btn(params, "Escolher...", self.on_browse).grid(row=0, column=2, sticky="ew", padx=5, pady=5)

        self._label(params, "Args extras para upload.py (opcional):").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.var_args = ctk.StringVar(value=""); self.ent_args = self._entry(params, textvariable=self.var_args)
        self.ent_args.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        self._label(params, "(ex.: --dry-run ou --tracker PTP)").grid(row=1, column=2, sticky="w", padx=5, pady=5)

        # Log viewer
        if USE_CTK:
            frame_log = ctk.CTkFrame(self); frame_log.pack(side="top", fill="both", expand=True, padx=10, pady=(0,10))
            self.txt = ctk.CTkTextbox(frame_log, wrap="word")
        else:
            frame_log = ctk.Frame(self); frame_log.pack(side="top", fill="both", expand=True, padx=10, pady=(0,10))
            from tkinter.scrolledtext import ScrolledText
            self.txt = ScrolledText(frame_log, wrap="word")
        self.txt.pack(side="left", fill="both", expand=True)
        if not USE_CTK:
            import tkinter as tk
            from tkinter import ttk
            sb = tk.Scrollbar(frame_log, command=self.txt.yview); sb.pack(side="right", fill="y")
            self.txt.configure(yscrollcommand=sb.set)

        self._init_prompt_ui()

        # Rodapé
        if USE_CTK: footer = ctk.CTkFrame(self)
        else:       footer = ctk.Frame(self)
        footer.pack(side="bottom", fill="x", padx=10, pady=10)
        self.lbl_footer = self._label(footer, f"APP_DIR: {APP_DIR}"); self.lbl_footer.pack(side="left")

    def _init_prompt_ui(self) -> None:
        if getattr(self, "prompt_container", None):
            return
        if USE_CTK:
            container = ctk.CTkFrame(self)
        else:
            container = ctk.Frame(self)
        self.prompt_container = container
        self.prompt_label = self._label(container, "")
        self.prompt_label.pack(side="top", fill="x", padx=10, pady=(6, 4))
        self.prompt_original_label = self._label(container, "")
        if USE_CTK:
            try:
                self.prompt_original_label.configure(text_color="#A0A0A0")
            except Exception:
                pass
        else:
            try:
                self.prompt_original_label.configure(fg="#666666", font=("TkDefaultFont", 9, "italic"))
            except Exception:
                pass
        self.prompt_original_label.pack(side="top", fill="x", padx=10, pady=(0, 4))
        self.prompt_original_label.pack_forget()
        if USE_CTK:
            body = ctk.CTkFrame(container)
        else:
            body = ctk.Frame(container)
        body.pack(fill="x", padx=10, pady=(4, 6))
        self.prompt_body = body
        if USE_CTK:
            actions = ctk.CTkFrame(container)
        else:
            actions = ctk.Frame(container)
        actions.pack(fill="x", padx=10, pady=(0, 10))
        self.prompt_actions = actions
        self.prompt_entry_var = None
        self.prompt_choice_var = None
        self.prompt_option_vars = []
        self.current_prompt_state = None
        self.hide_prompt_ui()
    # --- UI helpers

    def _btn(self, parent, text, command):
        if USE_CTK: return ctk.CTkButton(parent, text=text, command=command)
        import tkinter as tk
        return tk.Button(parent, text=text, command=command)

    def _label(self, parent, text):
        if USE_CTK: return ctk.CTkLabel(parent, text=text)
        import tkinter as tk
        return tk.Label(parent, text=text)

    def _entry(self, parent, textvariable, show: Optional[str] = None):
        if USE_CTK: return ctk.CTkEntry(parent, textvariable=textvariable, show=show)
        import tkinter as tk
        kwargs = {"textvariable": textvariable}
        if show:
            kwargs["show"] = show
        return tk.Entry(parent, **kwargs)

    def _focus_widget_safe(self, widget: Any) -> None:
        try:
            widget.focus_set()
        except Exception:
            pass

    def _scroll_log_to_end(self) -> None:
        try:
            self.txt.see("end")
        except Exception:
            pass

    def call_in_main_thread(self, func: Callable, *args, **kwargs) -> None:
        def wrapper() -> None:
            func(*args, **kwargs)
        try:
            self.after(0, wrapper)
        except Exception:
            wrapper()

    def _info(self, title: str, message: str) -> None:
        try: messagebox.showinfo(title, message)
        except Exception: pass

    def _error(self, title: str, message: str) -> None:
        try: messagebox.showerror(title, message)
        except Exception: pass



    def set_running_state(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        buttons = [self.btn_run, self.btn_wizard, self.btn_edit_cfg, self.btn_check, self.btn_install]
        for btn in buttons:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def start_upload(self, args: List[str]) -> None:
        if self.upload_runner and self.upload_runner.is_running():
            self._info("Upload", "Já existe um upload em execução.")
            return
        self.upload_runner = UploadRunner(self)
        self.upload_runner.start(args)

    def on_upload_started(self) -> None:
        self.append_log("Iniciando upload...")
        self.set_running_state(True)
        self.hide_prompt_ui()
        self.prompt_context_lines.clear()
        self.prompt_context_partial = ""

    def on_upload_output(self, chunk: str, stream: str = "stdout") -> None:
        if not chunk:
            return
        text = chunk.replace("\r\n", "\n").replace("\r", "\n")
        if stream == "stderr":
            text = self._format_stderr_chunk(text)
        if stream == "stdout":
            combined = f"{self.prompt_context_partial}{text}"
            segments = combined.split("\n")
            if combined.endswith("\n"):
                self.prompt_context_partial = ""
            else:
                self.prompt_context_partial = segments.pop()
            for segment in segments:
                stripped = segment.strip()
                if stripped:
                    self.prompt_context_lines.append(stripped)
                    self._append_prompt_context_line(stripped)
        try:
            self.txt.insert("end", text)
            self.txt.see("end")
        except Exception:
            pass

    def _format_stderr_chunk(self, chunk: str) -> str:
        return chunk  # mostrar exatamente como veio


    def request_prompt(self, prompt_type: str, message: str, resolver: Callable[[Any], None], **extra: Any) -> None:
        payload = dict(extra) if extra else {}
        self.call_in_main_thread(self._show_prompt, prompt_type, message, resolver, payload)

    def _clear_prompt_content(self) -> None:
        self._clear_prompt_bindings()
        if getattr(self, "prompt_body", None):
            for widget in list(self.prompt_body.children.values()):
                try:
                    widget.destroy()
                except Exception:
                    pass
        if getattr(self, "prompt_actions", None):
            for widget in list(self.prompt_actions.children.values()):
                try:
                    widget.destroy()
                except Exception:
                    pass
        self.prompt_option_vars = []
        self.prompt_entry_var = None
        self.prompt_choice_var = None

    def _clear_prompt_bindings(self) -> None:
        if not getattr(self, "_active_prompt_bindings", None):
            return
        for sequence in list(self._active_prompt_bindings):
            try:
                self.unbind(sequence)
            except Exception:
                pass
        self._active_prompt_bindings.clear()

    def _prompt_button(self, text: str, callback: Callable[[], None]) -> Any:
        btn = self._btn(self.prompt_actions, text, callback)
        btn.pack(side="left", padx=4, pady=4)
        return btn

    def _bind_prompt_key(self, sequence: str, handler: Callable[[], None]) -> None:
        def callback(_event: Any) -> str:
            handler()
            return "break"
        try:
            self.bind(sequence, callback)
            if sequence not in self._active_prompt_bindings:
                self._active_prompt_bindings.append(sequence)
        except Exception:
            pass

    def _update_prompt_labels(self) -> None:
        state = self.current_prompt_state or {}
        context_lines = state.get("context_lines") or []
        display_core = (state.get("display") or "").strip() or "Entrada necessaria"
        original_core = (state.get("original_display") or "").strip()
        text_parts: List[str] = []
        if context_lines:
            text_parts.append("\n".join(context_lines))
        if display_core:
            text_parts.append(display_core)
        composed = "\n\n".join(part for part in text_parts if part).strip() or "Entrada necessaria"
        if getattr(self, "prompt_label", None):
            try:
                self.prompt_label.configure(text=composed)
            except Exception:
                pass
        label = getattr(self, "prompt_original_label", None)
        if not label:
            return
        if original_core and original_core != display_core:
            try:
                label.configure(text=f"Original: {original_core}")
                label.pack(side="top", fill="x", padx=10, pady=(0, 4))
            except Exception:
                pass
        else:
            try:
                label.pack_forget()
            except Exception:
                pass

    def _append_prompt_context_line(self, text: str) -> None:
        state = self.current_prompt_state
        if not state:
            return
        context = state.setdefault("context_lines", [])
        if context and context[-1] == text:
            return
        context.append(text)
        max_lines = 8
        if len(context) > max_lines:
            del context[:-max_lines]
        self._update_prompt_labels()

    def _build_prompt_inline(self, prompt_mode: str, payload: Dict[str, Any]) -> None:
        self.prompt_entry_var = None
        self.prompt_choice_var = None
        self.prompt_option_vars = []

        if prompt_mode == "text":
            default_value = payload.get("default")
            is_password = bool(payload.get("is_password"))
            initial = default_value if isinstance(default_value, str) and not is_password else ""
            self.prompt_entry_var = ctk.StringVar(value=initial or "")
            entry = self._entry(self.prompt_body, self.prompt_entry_var, show="*" if is_password else None)
            entry.pack(fill="x", padx=10, pady=(0, 8))

            def submit() -> None:
                value = self.prompt_entry_var.get() if self.prompt_entry_var is not None else ""
                if value == "" and default_value is not None:
                    self._resolve_prompt(default_value)
                else:
                    self._resolve_prompt(value)

            entry.bind("<Return>", lambda _e: submit())
            entry.bind("<KP_Enter>", lambda _e: submit())
            entry.bind("<Escape>", lambda _e: self._resolve_prompt(CANCELLED_PROMPT))
            self.after(120, lambda: self._focus_widget_safe(entry))
            self._prompt_button("Enviar", submit)
            if default_value is not None and not is_password:
                if default_value == "":
                    self._prompt_button("Usar padrão (vazio)", lambda: self._resolve_prompt(default_value))
                else:
                    self._prompt_button(f"Usar padrão ({default_value})", lambda dv=default_value: self._resolve_prompt(dv))
            self._prompt_button("Cancelar", lambda: self._resolve_prompt(CANCELLED_PROMPT))
            return

        if prompt_mode == "yes_no":
            default_raw = payload.get("default")
            default_value = bool(default_raw) if default_raw is not None else None

            def choose_yes() -> None:
                self._resolve_prompt(True)

            def choose_no() -> None:
                self._resolve_prompt(False)

            btn_yes = self._prompt_button("Sim", choose_yes)
            self._prompt_button("Não", choose_no)
            if default_value is not None:
                texto = "Sim" if default_value else "Não"
                self._prompt_button(f"Padrão ({texto})", lambda dv=default_value: self._resolve_prompt(dv))
            self._prompt_button("Cancelar", lambda: self._resolve_prompt(CANCELLED_PROMPT))
            self.after(120, lambda: self._focus_widget_safe(btn_yes))

            enter_default = True if default_value is None else bool(default_value)

            self._bind_prompt_key("<Return>", lambda: self._resolve_prompt(enter_default))
            self._bind_prompt_key("<KP_Enter>", lambda: self._resolve_prompt(enter_default))
            self._bind_prompt_key("<Escape>", lambda: self._resolve_prompt(CANCELLED_PROMPT))
            for seq in ("<KeyPress-y>", "<KeyPress-Y>", "<KeyPress-s>", "<KeyPress-S>"):
                self._bind_prompt_key(seq, choose_yes)
            for seq in ("<KeyPress-n>", "<KeyPress-N>"):
                self._bind_prompt_key(seq, choose_no)
            return

        if prompt_mode == "choice":
            options = payload.get("options") or []
            if not options:
                self._resolve_prompt(None)
                return
            labels = [opt.get("label", str(opt.get("value"))) for opt in options]
            initial_label = labels[0] if labels else ""
            self.prompt_choice_var = ctk.StringVar(value=initial_label)
            combo = self._combo(self.prompt_body, self.prompt_choice_var, labels)
            combo.pack(fill="x", padx=10, pady=(0, 8))

            def submit_choice() -> None:
                label = self.prompt_choice_var.get() if self.prompt_choice_var is not None else ""
                selected = next((opt.get("value") for opt in options if opt.get("label") == label), None)
                self._resolve_prompt(selected)

            self._prompt_button("Selecionar", submit_choice)
            self._prompt_button("Cancelar", lambda: self._resolve_prompt(CANCELLED_PROMPT))
            self.after(150, lambda: self._focus_widget_safe(combo))
            self._bind_prompt_key("<Return>", submit_choice)
            self._bind_prompt_key("<KP_Enter>", submit_choice)
            self._bind_prompt_key("<Escape>", lambda: self._resolve_prompt(CANCELLED_PROMPT))
            return

        if prompt_mode == "multi_choice":
            options = payload.get("options") or []
            if not options:
                self._resolve_prompt(None)
                return
            for opt in options:
                var = ctk.BooleanVar(value=False)
                cb = self._check(self.prompt_body, opt.get("label", str(opt.get("value"))), var)
                cb.pack(anchor="w", padx=10, pady=2)
                self.prompt_option_vars.append((var, opt.get("value")))

            def submit_multi() -> None:
                selected = [value for var, value in self.prompt_option_vars if bool(var.get())]
                self._resolve_prompt(selected or None)

            self._prompt_button("Confirmar", submit_multi)
            self._prompt_button("Cancelar", lambda: self._resolve_prompt(CANCELLED_PROMPT))
            self._bind_prompt_key("<Return>", submit_multi)
            self._bind_prompt_key("<KP_Enter>", submit_multi)
            self._bind_prompt_key("<Escape>", lambda: self._resolve_prompt(CANCELLED_PROMPT))
            return

        self._resolve_prompt(None)

    def hide_prompt_ui(self) -> None:
        if getattr(self, "prompt_original_label", None):
            try:
                self.prompt_original_label.configure(text="")
                self.prompt_original_label.pack_forget()
            except Exception:
                pass
        if getattr(self, "prompt_container", None):
            try:
                self.prompt_container.pack_forget()
            except Exception:
                pass
        self._clear_prompt_content()
        if getattr(self, "prompt_label", None):
            try:
                self.prompt_label.configure(text="")
            except Exception:
                pass
        self.current_prompt_state = None

    def _consume_prompt_context(self, max_lines: int = 3) -> List[str]:
        if max_lines <= 0:
            max_lines = 1
        lines = list(self.prompt_context_lines)
        if not lines:
            return []
        selected = lines[-max_lines:]
        self.prompt_context_lines.clear()
        return selected

    def _show_prompt(self, prompt_type: str, message: str, resolver: Callable[[Any], None], extra: Dict[str, Any]) -> None:
        context_lines = self._consume_prompt_context()
        translated = translate_prompt_pt(message)
        display_core = translated if translated else (message or "Entrada necessaria")
        original_core = message or ""
        prompt_mode = prompt_type
        payload = dict(extra)
        if prompt_mode == "text":
            chosen_line: Optional[str] = None
            is_yes_no, inferred_default = detect_yes_no_prompt(original_core or display_core)
            if is_yes_no:
                chosen_line = original_core or display_core
            else:
                for candidate in reversed([c for c in context_lines if c]):
                    is_yes_no, inferred_default = detect_yes_no_prompt(candidate)
                    if is_yes_no:
                        chosen_line = candidate
                        break
            if is_yes_no:
                prompt_mode = "yes_no"
                payload = dict(payload)
                if inferred_default is not None:
                    payload["default"] = inferred_default
                if chosen_line:
                    if not (original_core or "").strip():
                        original_core = chosen_line
                    if display_core == "Entrada necessaria" or not display_core.strip():
                        display_core = chosen_line
        # For the GUI, always show a generic prompt label only.
        display_core = "Entrada necessaria"
        original_core = ""
        self.hide_prompt_ui()
        self.current_prompt_state = None
        state = {
            "resolver": resolver,
            "type": prompt_mode,
            "original_type": prompt_type,
            "message": message,
            "extra": payload,
            "display": display_core,
            "original_display": original_core,
            "context_lines": list(context_lines),
        }
        self.current_prompt_state = state
        if getattr(self, "prompt_container", None):
            try:
                self.prompt_container.pack(side="top", fill="x", padx=10, pady=(0, 10))
            except Exception:
                pass
        self._build_prompt_inline(prompt_mode, payload)
        self._update_prompt_labels()
        self._scroll_log_to_end()
        self.after(100, self._scroll_log_to_end)

    def _resolve_prompt(self, value: Any) -> None:
        state = self.current_prompt_state or {}
        resolver = state.get("resolver")
        original_type = state.get("original_type")
        current_type = state.get("type")
        if (
            original_type == "text"
            and current_type == "yes_no"
            and value not in (CANCELLED_PROMPT, None)
        ):
            if value is True:
                value = "y"
            elif value is False:
                value = "n"
        try:
            if resolver:
                resolver(value)
        finally:
            if value not in (None, CANCELLED_PROMPT):
                try:
                    self.append_log("")
                except Exception:
                    pass
            self.current_prompt_state = None
            self.hide_prompt_ui()
            self.prompt_context_lines.clear()
            self.prompt_context_partial = ""

    def on_upload_finished(self, rc: int, stdout_text: str, stderr_text: str, error: Optional[Exception] = None) -> None:
        self.set_running_state(False)
        self.hide_prompt_ui()
        self.upload_runner = None
        self.append_log(f"Processo finalizado com codigo: {rc}")

        if rc == 0 and not error:
            self._info("Processo concluído", "Finalizado...")
        else:
            self.show_full_error(stderr_text, stdout_text, rc, error)

        self.refresh_status_async()
 
    def show_full_error(self, stderr_text: str, stdout_text: str, rc: int, error: Optional[Exception]) -> None:
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText

        win = tk.Toplevel(self)
        win.title("Erros completos do Upload")
        win.geometry("900x600")
        tk.Label(win, text=f"Código de saída: {rc}").pack(anchor="w", padx=8, pady=(8,2))
        if error:
            tk.Label(win, text=f"Exceção: {error!r}").pack(anchor="w", padx=8, pady=(0,8))

        nb = tk.Frame(win); nb.pack(fill="both", expand=True, padx=8, pady=8)

        # STDERR
        frm_err = tk.Frame(nb); frm_err.pack(fill="both", expand=True)
        tk.Label(frm_err, text="STDERR (completo):").pack(anchor="w")
        txt_err = ScrolledText(frm_err, wrap="none")
        txt_err.pack(fill="both", expand=True)
        txt_err.insert("end", stderr_text or "<STDERR vazio>\n")

        # STDOUT (opcional)
        frm_out = tk.Frame(nb); frm_out.pack(fill="both", expand=True)
        tk.Label(frm_out, text="STDOUT (completo):").pack(anchor="w")
        txt_out = ScrolledText(frm_out, wrap="none")
        txt_out.pack(fill="both", expand=True)
        txt_out.insert("end", stdout_text or "<STDOUT vazio>\n")

        btn_row = tk.Frame(win); btn_row.pack(fill="x", padx=8, pady=8)
        def _copy_all():
            try:
                full = f"=== STDERR ===\n{stderr_text}\n\n=== STDOUT ===\n{stdout_text}"
                win.clipboard_clear(); win.clipboard_append(full)
            except Exception:
                pass
        tk.Button(btn_row, text="Copiar tudo", command=_copy_all).pack(side="left")
        tk.Button(btn_row, text="Fechar", command=win.destroy).pack(side="right")


    # --- Botões

    def on_check_deps(self) -> None:
        self.append_log("Checando dependências...")
        self.refresh_status_async()

    def on_install_deps(self) -> None:
        # No executável: só FFmpeg/MediaInfo (as libs Python já vêm no bundle)
        if running_frozen():
            self._info(
                "Dependências",
                "Este executável já inclui as dependências Python.\n"
                "Vou verificar/instalar apenas FFmpeg/MediaInfo."
            )
        self.append_log("Instalando/verificando FFmpeg/MediaInfo (offline→online, com progresso)...")
        self.install_deps_with_progress()

    def on_open_wizard(self) -> None:
        ensure_config_generated(overwrite_if_missing=False)
        wiz = Wizard(self)
        wiz.center_on_parent()

    def on_browse(self) -> None:
        try:
            path = filedialog.askopenfilename(title="Escolher arquivo de mídia")
            if not path:
                path = filedialog.askdirectory(title="Escolher pasta de mídia")
            if path: self.var_path.set(path)
        except Exception as e:
            self._error("Erro", f"Falha ao selecionar caminho: {e}")

    def on_edit_config(self) -> None:
        ok, msg = ensure_config_generated(overwrite_if_missing=False)
        if not ok:
            self._error("Config", f"Config ausente: {msg}")
            return
        try:
            editor = ConfigEditor(self)
            editor.center_on_parent()
        except Exception as e:
            self._error("Erro", f"Nao consegui abrir o editor de config.\n{e}")

    def on_open_logs(self) -> None:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if os.name == "nt": os.startfile(str(LOG_DIR))  # type: ignore[attr-defined]
            elif sys.platform == "darwin": subprocess.Popen(["open", str(LOG_DIR)])
            else: subprocess.Popen(["xdg-open", str(LOG_DIR)])
        except Exception as e:
            self._error("Erro", f"Não consegui abrir a pasta de logs.\n{e}")

    def on_run(self) -> None:


        path = self.var_path.get().strip()
        if not path:
            self._error("Faltam dados", "Informe o caminho de arquivo ou pasta de mídia.")
            return

        ok, msg = ensure_config_generated(overwrite_if_missing=False)
        if not ok:
            self._error("Config", f"Config ausente: {msg}")
            return

        ff, fp = find_ffmpeg_binaries(); mi = find_mediainfo_binary()
        if not (ff and fp and mi):
            self._info("Dependências",
                       "FFmpeg e/ou MediaInfo ausentes. O app instala automaticamente ao iniciar "
                       "ou use o botão 'Instalar dependências'.")
            return

        ok_shadow, msg_shadow = ensure_ua_runtime_layout()
        if not ok_shadow:
            self._error("Config", f"Não consegui preparar config para o upload.py.\n{msg_shadow}")
            return


        extra = self.var_args.get().strip()
        args = shlex_split(extra) if extra else []
        if "--path" not in args:
            args += ["--path", path]

        self.start_upload(args)

    # --- Status/log

    def refresh_status_async(self) -> None:
        threading.Thread(target=self.refresh_status, daemon=True).start()

    def refresh_status(self) -> None:
        ff, fp = find_ffmpeg_binaries()
        mi = find_mediainfo_binary()
        ff_ok = bool(ff and fp)
        mi_ok = bool(mi)

        def apply():
            self.ffmpeg_ok = ff_ok
            self.mediainfo_ok = mi_ok
            self.set_status_labels(ff_ok, mi_ok)
            self.log_dependency_status(ff, fp, mi)

        try:
            self.after(0, apply)
        except Exception:
            apply()

    def set_status_labels(self, ff_ok: bool, mi_ok: bool) -> None:
        self.lbl_ffmpeg.configure(text=f"FFmpeg: {'OK' if ff_ok else 'nao encontrado'}")
        self.lbl_mediainfo.configure(text=f"MediaInfo: {'OK' if mi_ok else 'nao encontrado'}")
        cfg = DATA_DIR / "config.py"
        self.lbl_config.configure(text=f"Config: {'OK' if cfg.exists() else 'ausente'} ({cfg})")

    def log_dependency_status(self, ff_path: Optional[str], fp_path: Optional[str], mi_path: Optional[str]) -> None:
        ff_status = ff_path or "nao encontrado"
        fp_status = fp_path or "nao encontrado"
        mi_status = mi_path or "nao encontrado"
        self.append_log(f"FFmpeg executavel: {ff_status}")
        self.append_log(f"FFprobe executavel: {fp_status}")
        self.append_log(f"MediaInfo executavel: {mi_status}")

    def append_log(self, text: str) -> None:
        write_log(text)
        try:
            self.txt.insert("end", text + "\n"); self.txt.see("end")
        except Exception:
            pass

    # --- Checagem automática ao iniciar (popup + progresso)

    def startup_check(self) -> None:
        def check_and_prompt():
            self.append_log("Checando dependências ao iniciar...")
            ok_ff = bool(find_ffmpeg_binaries()[0] and find_ffmpeg_binaries()[1])
            ok_mi = bool(find_mediainfo_binary())
            if ok_ff and ok_mi:
                self.refresh_status()
                return

            # tenta offline
            self.append_log("Tentando preparar dependências em modo offline...")
            prepare_ffmpeg_offline()
            prepare_mediainfo_offline()
            ok_ff = bool(find_ffmpeg_binaries()[0] and find_ffmpeg_binaries()[1])
            ok_mi = bool(find_mediainfo_binary())
            if ok_ff and ok_mi:
                self.refresh_status()
                return

            # pergunta para baixar
            def ask_install():
                try:
                    return messagebox.askyesno(
                        "Dependências ausentes",
                        "FFmpeg e/ou MediaInfo não encontrados.\n\nDeseja baixar e instalar agora automaticamente?"
                    )
                except Exception:
                    return True
            if ask_install():
                self.install_deps_with_progress()
            else:
                self.append_log("Usuário optou por não instalar dependências agora.")
                self.refresh_status()
        threading.Thread(target=check_and_prompt, daemon=True).start()

    # --- Instalação com progresso

    def install_deps_with_progress(self):
        dlg = ProgressDialog(self, "Instalando dependências...")
        def progress_cb(msg: str, ratio: float, extra: str):
            try:
                self.after(0, dlg.update_progress, msg, ratio, extra)
            except Exception:
                pass

        def worker():
            errors: List[str] = []
            # OFFLINE → ONLINE
            progress_cb("Verificando dependências (offline)", 0.02, "")
            off_ff = prepare_ffmpeg_offline(progress_cb)
            off_mi = prepare_mediainfo_offline(progress_cb)
            need_ff = not bool(find_ffmpeg_binaries()[0] and find_ffmpeg_binaries()[1])
            need_mi = not bool(find_mediainfo_binary())

            if need_ff or need_mi:
                if not has_internet():
                    errors.append("Sem conexão com a internet para baixar dependências.")
                else:
                    if need_ff:
                        ok, err = download_and_install_ffmpeg_online(progress_cb)
                        if not ok: errors.append(err or "Falha ao instalar FFmpeg.")
                    if need_mi:
                        ok, err = download_and_install_mediainfo_online(progress_cb)
                        if not ok: errors.append(err or "Falha ao instalar MediaInfo.")

            # Resultado
            self.refresh_status()
            if errors:
                err_text = "\n".join(e for e in errors if e)
                write_log(f"Instalação finalizada com erros: {err_text}")
                self.after(0, dlg.done, err_text)
                self.after(0, lambda: self._error("Falha na instalação", f"Ocorreu(m) erro(s):\n\n{err_text}\n\nVeja também os logs em:\n{LOG_DIR}"))
            else:
                self.after(0, dlg.done, None)
        threading.Thread(target=worker, daemon=True).start()

# ---------------------------
# Assistente de Configuração (essencial)
# ---------------------------
# ---------------------------
# Assistente de Configuração (essencial)
# ---------------------------

IMG_HOSTS = {
    "imgbb": {"fields": ["imgbb_api"]},
    "ptpimg": {"fields": ["ptpimg_api"]},
    "ziplinestudio": {"fields": ["zipline_url", "zipline_api_key"]},
    "imgbox": {"fields": []},
    "pixhost": {"fields": []},
}

class ConfigEditor(ctk.CTkToplevel if USE_CTK else ctk.Toplevel):  # type: ignore[misc]
    def __init__(self, master: "App"):
        super().__init__(master)
        self.title("Editor de config.py")
        self.geometry("900x520")
        self.transient(master)
        self.grab_set()

        self.cfg_path = DATA_DIR / "config.py"
        try:
            current_text = self.cfg_path.read_text(encoding="utf-8")
        except Exception:
            current_text = ""

        if USE_CTK:
            container = ctk.CTkFrame(self)
        else:
            container = ctk.Frame(self)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        info_text = f"Editando: {self.cfg_path}"
        if USE_CTK:
            info_label = ctk.CTkLabel(container, text=info_text, anchor="w")
        else:
            import tkinter as tk
            info_label = tk.Label(container, text=info_text, anchor="w")
        info_label.pack(side="top", fill="x")

        if USE_CTK:
            self.txt = ctk.CTkTextbox(container, wrap="none")
        else:
            from tkinter.scrolledtext import ScrolledText
            self.txt = ScrolledText(container, wrap="none")
        self.txt.pack(side="top", fill="both", expand=True, pady=(8, 10))
        self.txt.insert("1.0", current_text)

        if USE_CTK:
            btn_row = ctk.CTkFrame(container)
        else:
            btn_row = ctk.Frame(container)
        btn_row.pack(side="bottom", fill="x")

        btn_kwargs = dict(padx=5)
        if USE_CTK:
            ctk.CTkButton(btn_row, text="Salvar", command=self.on_save).pack(side="left", **btn_kwargs)
            ctk.CTkButton(btn_row, text="Fechar", command=self.destroy).pack(side="left", **btn_kwargs)
        else:
            import tkinter as tk
            tk.Button(btn_row, text="Salvar", command=self.on_save).pack(side="left", **btn_kwargs)
            tk.Button(btn_row, text="Fechar", command=self.destroy).pack(side="left", **btn_kwargs)

    def center_on_parent(self):
        try:
            self.update_idletasks()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w = self.winfo_width()
            h = self.winfo_height()
            x = int((sw - w) / 2)
            y = int((sh - h) / 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def on_save(self):
        text = self.txt.get("1.0", "end-1c")
        if not text.endswith("\n"):
            text += "\n"
        try:
            self.cfg_path.write_text(text, encoding="utf-8")
            messagebox.showinfo("Config", "config.py salvo com sucesso.")
            try:
                cfg = DATA_DIR / "config.py"
                if hasattr(self.master, "lbl_config"):
                    status = "OK" if cfg.exists() else "ausente"
                    self.master.lbl_config.configure(text=f"Config: {status} ({cfg})")
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao salvar o config.py.\n{e}")

class Wizard(ctk.CTkToplevel if USE_CTK else ctk.Toplevel):  # type: ignore[misc]
    def __init__(self, master: "App"):
        super().__init__(master)
        self.title("Assistente de Configuração - Essencial")
        self.geometry("720x540")
        self.transient(master)
        self.grab_set()

        self.cfg, self.cfg_path = load_existing_config_dict()
        if not isinstance(self.cfg, dict):
            self.cfg = {}

        self.default_client_name = (self.cfg.get("DEFAULT", {}) or {}).get("default_torrent_client", "qbittorrent")

        self.var_tmdb = ctk.StringVar(value=(self.cfg.get("DEFAULT", {}) or {}).get("tmdb_api", ""))
        self.var_img_host = ctk.StringVar(value=(self.cfg.get("DEFAULT", {}) or {}).get("img_host_1", "imgbb"))
        self.var_imgbb_api = ctk.StringVar(value=(self.cfg.get("DEFAULT", {}) or {}).get("imgbb_api", ""))
        self.var_ptpimg_api = ctk.StringVar(value=(self.cfg.get("DEFAULT", {}) or {}).get("ptpimg_api", ""))
        self.var_zipline_url = ctk.StringVar(value=(self.cfg.get("DEFAULT", {}) or {}).get("zipline_url", ""))
        self.var_zipline_key = ctk.StringVar(value=(self.cfg.get("DEFAULT", {}) or {}).get("zipline_api_key", ""))

        trackers_cfg = self.cfg.get("TRACKERS", {}) or {}
        default_trackers = str(trackers_cfg.get("default_trackers", "") or "").strip()
        if not default_trackers:
            default_trackers = "SAM"
        self.var_trackers = ctk.StringVar(value=default_trackers)

        sam_raw = trackers_cfg.get("SAM", {})
        if not isinstance(sam_raw, dict):
            sam_raw = {}
        self.var_sam_link_dir = ctk.StringVar(value=sam_raw.get("link_dir_name", ""))
        self.var_sam_api_key = ctk.StringVar(value=sam_raw.get("api_key", ""))
        self.var_sam_anon = ctk.BooleanVar(value=bool(sam_raw.get("anon", False)))

        clients = self.cfg.get("TORRENT_CLIENTS", {}) or {}
        qb = clients.get("qbittorrent", {}) or {}

        raw_url = str(qb.get("qbit_url") or qb.get("host") or "").strip()
        if raw_url and not raw_url.lower().startswith(("http://", "https://")):
            raw_url = f"http://{raw_url}"
        if not raw_url:
            raw_url = "http://127.0.0.1"
        qbit_port = str(qb.get("qbit_port") or qb.get("port") or "8080").strip() or "8080"
        qbit_user = str(qb.get("qbit_user") or qb.get("username") or "admin")
        qbit_pass = str(qb.get("qbit_pass") or qb.get("password") or "adminadmin")
        qbit_cat = str(qb.get("qbit_cat") or qb.get("category") or "uploads")

        self.var_qb_host = ctk.StringVar(value=raw_url)
        self.var_qb_port = ctk.StringVar(value=qbit_port)
        self.var_qb_user = ctk.StringVar(value=qbit_user)
        self.var_qb_pass = ctk.StringVar(value=qbit_pass)
        self.var_qb_category = ctk.StringVar(value=qbit_cat)
        self.var_avatar = ctk.StringVar(value=(self.cfg.get("DEFAULT", {}) or {}).get("uploader_avatar", ""))
        self.var_use_discord = ctk.BooleanVar(value=(self.cfg.get("DISCORD", {}) or {}).get("use_discord", False))

        self.content = self._create_scrollable_container()
        self.build_layout()

    def center_on_parent(self):
        try:
            self.update_idletasks()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w = self.winfo_width()
            h = self.winfo_height()
            x = int((sw - w) / 2)
            y = int((sh - h) / 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _create_scrollable_container(self):
        if USE_CTK:
            container = ctk.CTkScrollableFrame(self)
            container.pack(fill="both", expand=True, padx=10, pady=10)
            return container
        import tkinter as tk
        outer = tk.Frame(self)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        inner = tk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, width=canvas.winfo_width())

        inner.bind("<Configure>", _on_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(widget):
            widget.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
            widget.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        _bind_mousewheel(inner)
        return inner

    def build_layout(self):
        pad = dict(padx=10, pady=6)
        frame_def = self._frame(self.content, "Configuração Básica")
        frame_def.pack(fill="x", **pad)

        self._labeled_entry(frame_def, "TMDB API", self.var_tmdb).pack(fill="x", **pad)

        row = self._row(frame_def)
        self._label(row, "Hospedeiro de imagens")
        row.pack(fill="x", **pad)
        host_combo = self._combo(row, self.var_img_host, list(IMG_HOSTS.keys()), self.on_change_img_host)
        host_combo.pack(side="left", padx=6)

        self.host_fields_frame = self._frame(frame_def)
        self.host_fields_frame.pack(fill="x", padx=10, pady=(0,10))
        self.render_host_fields()

        frame_tr = self._frame(self.content, "Trackers padrao")
        frame_tr.pack(fill="x", **pad)
        self._labeled_entry(frame_tr, "default_trackers (ex.: BHD, PTP, TL)", self.var_trackers).pack(fill="x", **pad)

        frame_sam = self._frame(self.content, "Tracker SAM (Samaritano)")
        frame_sam.pack(fill="x", **pad)
        self._labeled_entry(frame_sam, "link_dir_name", self.var_sam_link_dir).pack(fill="x", **pad)
        self._labeled_entry(frame_sam, "api_key", self.var_sam_api_key).pack(fill="x", **pad)
        self._check(frame_sam, "Upload anonimo (anon)", self.var_sam_anon).pack(anchor="w", **pad)

        frame_qb = self._frame(self.content, "Cliente qBittorrent (default)")
        frame_qb.pack(fill="x", **pad)
        self._labeled_entry(frame_qb, "Host", self.var_qb_host).pack(fill="x", **pad)
        self._labeled_entry(frame_qb, "Porta", self.var_qb_port).pack(fill="x", **pad)
        self._labeled_entry(frame_qb, "Usuário", self.var_qb_user).pack(fill="x", **pad)
        self._labeled_entry(frame_qb, "Senha", self.var_qb_pass, show="*").pack(fill="x", **pad)
        self._labeled_entry(frame_qb, "Categoria", self.var_qb_category).pack(fill="x", **pad)

        frame_sig = self._frame(self.content, "Assinatura do Upload")
        frame_sig.pack(fill="x", **pad)
        self._label(frame_sig, "As linhas abaixo dos screenshots serão preenchidas automaticamente.").pack(anchor="w", **pad)
        self._labeled_entry(frame_sig, "Avatar (URL opcional)", self.var_avatar).pack(fill="x", **pad)

        frame_dc = self._frame(self.content, "Discord (opcional)")
        frame_dc.pack(fill="x", **pad)
        self._check(frame_dc, "Ativar notificações via Discord (use_discord)", self.var_use_discord).pack(anchor="w", **pad)

        actions = self._frame(self.content)
        actions.pack(fill="x", **pad)
        self._btn(actions, "Salvar configurações", self.on_save).pack(side="left", padx=6)
        self._btn(actions, "Fechar", self.destroy).pack(side="left", padx=6)

    def _frame(self, parent, title: Optional[str] = None):
        if USE_CTK:
            f = ctk.CTkFrame(parent)
            if title:
                ctk.CTkLabel(f, text=title, font=("TkDefaultFont", 14, "bold")).pack(anchor="w", padx=10, pady=(8,0))
            return f
        import tkinter as tk
        f = ctk.Frame(parent)
        if title:
            lbl = tk.Label(f, text=title, font=("TkDefaultFont", 10, "bold"))
            lbl.pack(anchor="w", padx=10, pady=(8,0))
        return f

    def _row(self, parent):
        if USE_CTK:
            return ctk.CTkFrame(parent)
        import tkinter as tk
        return tk.Frame(parent)

    def _label(self, parent, text):
        if USE_CTK:
            return ctk.CTkLabel(parent, text=text)
        import tkinter as tk
        return tk.Label(parent, text=text)

    def _entry(self, parent, textvariable, show: Optional[str] = None):
        if USE_CTK:
            return ctk.CTkEntry(parent, textvariable=textvariable, show=show)
        import tkinter as tk
        return tk.Entry(parent, textvariable=textvariable, show=show)

    def _combo(self, parent, var, values, callback=None):
        if USE_CTK:
            combo = ctk.CTkComboBox(parent, variable=var, values=values, command=lambda _: callback() if callback else None, state="readonly")
            return combo
        import tkinter as tk
        from tkinter import ttk
        combo = ttk.Combobox(parent, textvariable=var, values=values, state="readonly")
        if callback:
            combo.bind("<<ComboboxSelected>>", lambda _e: callback())
        return combo

    def _check(self, parent, text, var):
        if USE_CTK:
            return ctk.CTkCheckBox(parent, text=text, variable=var)
        import tkinter as tk
        return tk.Checkbutton(parent, text=text, variable=var, onvalue=True, offvalue=False)

    def _btn(self, parent, text, command):
        if USE_CTK:
            return ctk.CTkButton(parent, text=text, command=command)
        import tkinter as tk
        return tk.Button(parent, text=text, command=command)

    def _labeled_entry(self, parent, label, var, show: Optional[str] = None):
        fr = self._row(parent)
        self._label(fr, label).pack(side="left", padx=6)
        self._entry(fr, var, show=show).pack(side="left", fill="x", expand=True, padx=6)
        return fr

    def clear_frame(self, frame):
        for w in list(frame.children.values()):
            try:
                w.destroy()
            except Exception:
                pass

    def render_host_fields(self):
        self.clear_frame(self.host_fields_frame)
        host = self.var_img_host.get().strip().lower()
        fields = IMG_HOSTS.get(host, {}).get("fields", [])
        if not fields:
            self._label(self.host_fields_frame, f"{host} nao requer API key.").pack(anchor="w", padx=6, pady=4)
            return
        for field in fields:
            var = {
                "imgbb_api": self.var_imgbb_api,
                "ptpimg_api": self.var_ptpimg_api,
                "zipline_url": self.var_zipline_url,
                "zipline_api_key": self.var_zipline_key,
            }.get(field)
            if var is None:
                continue
            label = field.replace("_", " ")
            self._labeled_entry(self.host_fields_frame, label, var).pack(fill="x", padx=6, pady=4)

    def on_change_img_host(self):
        self.render_host_fields()

    def on_save(self):
        DEFAULT = (self.cfg.get("DEFAULT", {}) or {}).copy()
        TRACKERS = (self.cfg.get("TRACKERS", {}) or {}).copy()
        TORRENT_CLIENTS = (self.cfg.get("TORRENT_CLIENTS", {}) or {}).copy()
        DISCORD = (self.cfg.get("DISCORD", {}) or {}).copy()

        DEFAULT["tmdb_api"] = self.var_tmdb.get().strip()
        DEFAULT["img_host_1"] = self.var_img_host.get().strip().lower()
        for k in ["imgbb_api", "ptpimg_api", "zipline_url", "zipline_api_key"]:
            DEFAULT.pop(k, None)
        host = DEFAULT["img_host_1"]
        if host == "imgbb":
            DEFAULT["imgbb_api"] = self.var_imgbb_api.get().strip()
        elif host == "ptpimg":
            DEFAULT["ptpimg_api"] = self.var_ptpimg_api.get().strip()
        elif host == "ziplinestudio":
            DEFAULT["zipline_url"] = self.var_zipline_url.get().strip()
            DEFAULT["zipline_api_key"] = self.var_zipline_key.get().strip()

        DEFAULT["default_torrent_client"] = "qbittorrent"
        TRACKERS["default_trackers"] = self.var_trackers.get().strip() or "SAM"

        sam_existing = TRACKERS.get("SAM", {})
        if not isinstance(sam_existing, dict):
            sam_existing = {}
        sam_cfg = sam_existing.copy()
        sam_cfg["link_dir_name"] = self.var_sam_link_dir.get().strip()
        sam_cfg["api_key"] = self.var_sam_api_key.get().strip()
        sam_cfg["anon"] = bool(self.var_sam_anon.get())
        TRACKERS["SAM"] = sam_cfg

        qb = (TORRENT_CLIENTS.get("qbittorrent", {}) or {}).copy()
        host_input = self.var_qb_host.get().strip()
        if not host_input:
            host_input = "http://127.0.0.1"
        if not host_input.lower().startswith(("http://", "https://")):
            qbit_url = f"http://{host_input}"
        else:
            qbit_url = host_input
        qbit_url = qbit_url.rstrip("/")
        host_clean = qbit_url
        if host_clean.lower().startswith("http://"):
            host_clean = host_clean[7:]
        elif host_clean.lower().startswith("https://"):
            host_clean = host_clean[8:]
        host_clean = host_clean.rstrip("/\\") or "127.0.0.1"

        port_raw = self.var_qb_port.get().strip() or "8080"
        try:
            port_int = int(port_raw)
        except Exception:
            port_int = 8080
        user = self.var_qb_user.get().strip() or "admin"
        password = self.var_qb_pass.get().strip() or "adminadmin"
        category = self.var_qb_category.get().strip() or "uploads"

        qb["torrent_client"] = "qbit"
        qb["qbit_url"] = qbit_url
        qb["host"] = host_clean
        qb["qbit_port"] = str(port_int)
        qb["port"] = port_int
        qb["qbit_user"] = user
        qb["username"] = user
        qb["qbit_pass"] = password
        qb["password"] = password
        qb["category"] = category
        qb["qbit_cat"] = category
        TORRENT_CLIENTS["qbittorrent"] = qb

        DEFAULT["ua_signature_text"] = "Samaritano Upload-Assistant."
        DEFAULT["ua_signature_link"] = "https://github.com/Yabai1970/SamUploadAssistantGUI"
        DEFAULT["ua_signature_subtext"] = "Ramificação do L4G's e Audionut, adicionado traduções e GUI."
        DEFAULT["uploader_avatar"] = self.var_avatar.get().strip()

        DISCORD["use_discord"] = bool(self.var_use_discord.get())

        cfg_out = {
            "DEFAULT": DEFAULT,
            "TRACKERS": TRACKERS,
            "TORRENT_CLIENTS": TORRENT_CLIENTS,
            "DISCORD": DISCORD,
        }

        ok = save_config_dict(cfg_out, self.cfg_path)
        if ok:
            messagebox.showinfo("Configuração", f"Config salva em {self.cfg_path or (DATA_DIR/'config.py')}")
            self.destroy()
        else:
            messagebox.showerror("Erro", "Não foi possível salvar a configuração. Veja os logs.")


# ---------------------------
# Auxiliares diversos
# ---------------------------

def shlex_split(s: str) -> List[str]:
    import shlex
    try:
        return shlex.split(s)
    except Exception:
        return s.split()

def build_env_with_bins() -> Dict[str, str]:
    env = os.environ.copy()
    env.setdefault("UA_BASE_DIR", str(APP_DIR))  # era BUNDLE_DIR
    # PATH prioriza BIN_DIR e resources/*
    bin_ffmpeg = BIN_DIR / "ffmpeg"
    bin_mediainfo = BIN_DIR / "mediainfo"
    extra_paths = [
        str(BIN_DIR),
        str(bin_ffmpeg),
        str(bin_mediainfo),
        str(RES_DIR / "ffmpeg"),
        str(RES_DIR / "mediainfo"),
    ]
    seen: set[str] = set()
    unique_paths: List[str] = []
    for path in extra_paths:
        if path and path not in seen:
            seen.add(path)
            unique_paths.append(path)
    existing_path = env.get("PATH", "")
    if existing_path:
        unique_paths.append(existing_path)
    env["PATH"] = os.pathsep.join(unique_paths)

    # libs dinâmicas
    lib_paths = os.pathsep.join(unique_paths[:-1]) if len(unique_paths) > 1 else ""
    for key in ["LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"]:
        current = env.get(key, "")
        if current and lib_paths:
            env[key] = os.pathsep.join([lib_paths, current])
        elif lib_paths:
            env[key] = lib_paths

    # Variáveis auxiliares explícitas
    if os.name == "nt":
        ffmpeg_exe = bin_ffmpeg / "ffmpeg.exe"
        ffprobe_exe = bin_ffmpeg / "ffprobe.exe"
        mediainfo_exe = bin_mediainfo / "mediainfo.exe"
    else:
        ffmpeg_exe = bin_ffmpeg / "ffmpeg"
        ffprobe_exe = bin_ffmpeg / "ffprobe"
        mediainfo_exe = bin_mediainfo / "mediainfo"
    if ffmpeg_exe.exists():
        env.setdefault("FFMPEG_BIN", str(ffmpeg_exe))
        env.setdefault("FFMPEG_PATH", str(ffmpeg_exe))
    if ffprobe_exe.exists():
        env.setdefault("FFPROBE_BIN", str(ffprobe_exe))
    if mediainfo_exe.exists():
        env.setdefault("MEDIAINFO_BIN", str(mediainfo_exe))

    # Indica ao UA onde está o base_dir (raiz do pacote no runtime)
    env.setdefault("UA_BASE_DIR", str(BUNDLE_DIR))
    return env

# ---------------------------
# main
# ---------------------------

def main() -> int:
    try:
        app = App()
        try:
            app.after(0, lambda: app.state('zoomed'))
        except Exception:
            pass
        app.mainloop()

        return 0
    except Exception as e:
        write_log(f"Erro na GUI: {e}\n{traceback.format_exc()}")
        try:
            messagebox.showerror("Erro fatal", f"Ocorreu um erro inesperado.\n\n{e}\n\nVeja os logs em:\n{LOG_DIR}")
        except Exception:
            pass
        return 1

if __name__ == "__main__":
    if sys.platform == "win32":
        multiprocessing.freeze_support()
    sys.exit(main())
