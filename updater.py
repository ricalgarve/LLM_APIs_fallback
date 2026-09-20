"""
Módulo de Verificação e Auto-Atualização do Knowledge Ship.
Consulta a API do GitHub, compara versões semânticas e realiza o download e substituição atômica do executável.
"""

import os
import re
import sys
import json
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Callable

from version import __version__

GITHUB_REPO = "ricalgarve/LLM_APIs_fallback"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RAW_VERSION = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.py"


@dataclass
class UpdateInfo:
    has_update: bool
    current_version: str
    latest_version: str
    release_notes: str
    download_url: Optional[str] = None
    html_url: Optional[str] = None
    error_message: Optional[str] = None


def parse_version(ver_str: str) -> Tuple[int, ...]:
    """Extrai uma tupla de números inteiros de uma string de versão (ex: 'v1.2.3' -> (1, 2, 3))."""
    ver_clean = re.sub(r"^[vV]", "", (ver_str or "").strip())
    # Extrai grupos numéricos
    nums = re.findall(r"\d+", ver_clean)
    if not nums:
        return (0, 0, 0)
    return tuple(int(n) for n in nums[:4])


def check_for_updates(timeout: float = 5.0) -> UpdateInfo:
    """
    Consulta o GitHub para verificar se há uma versão mais recente que a atual.
    Tenta primeiro a API de Releases do GitHub e, se não houver release formal, o version.py do branch main.
    """
    current_tuple = parse_version(__version__)
    headers = {
        "User-Agent": "KnowledgeShip-AutoUpdater",
        "Accept": "application/vnd.github.v3+json",
    }

    # 1. Tenta API de Releases oficiais do GitHub
    try:
        req = urllib.request.Request(GITHUB_API_LATEST, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                tag_name = data.get("tag_name", "")
                remote_tuple = parse_version(tag_name)
                release_notes = data.get("body", "") or "Sem notas de versão fornecidas."
                html_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest")

                # Localiza asset executável (KnowledgeShip.exe)
                download_url = None
                for asset in data.get("assets", []):
                    name = asset.get("name", "").lower()
                    if name.endswith(".exe"):
                        download_url = asset.get("browser_download_url")
                        break

                has_update = remote_tuple > current_tuple
                return UpdateInfo(
                    has_update=has_update,
                    current_version=__version__,
                    latest_version=tag_name.lstrip("vV"),
                    release_notes=release_notes,
                    download_url=download_url,
                    html_url=html_url,
                )
    except urllib.error.HTTPError as e:
        # 404 significa que ainda não há releases formais criados no repositório
        if e.code != 404:
            return UpdateInfo(
                has_update=False,
                current_version=__version__,
                latest_version=__version__,
                release_notes="",
                error_message=f"HTTP {e.code}: {e.reason}",
            )
    except Exception as e:
        pass

    # 2. Fallback: Consulta o version.py diretamente na branch main
    try:
        req = urllib.request.Request(GITHUB_RAW_VERSION, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                content = resp.read().decode("utf-8")
                match = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)[\'"]', content)
                if match:
                    remote_ver = match.group(1).strip()
                    remote_tuple = parse_version(remote_ver)
                    has_update = remote_tuple > current_tuple
                    return UpdateInfo(
                        has_update=has_update,
                        current_version=__version__,
                        latest_version=remote_ver,
                        release_notes="Nova versão disponível no repositório GitHub.",
                        download_url=f"https://github.com/{GITHUB_REPO}/raw/main/releases/KnowledgeShip.exe",
                        html_url=f"https://github.com/{GITHUB_REPO}",
                    )
    except Exception as e:
        return UpdateInfo(
            has_update=False,
            current_version=__version__,
            latest_version=__version__,
            release_notes="",
            error_message=str(e),
        )

    return UpdateInfo(
        has_update=False,
        current_version=__version__,
        latest_version=__version__,
        release_notes="Você já está utilizando a versão mais recente.",
    )


def download_file_with_progress(
    url: str,
    dest_path: Path,
    progress_callback: Optional[Callable[[float, float, float], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    chunk_size: int = 65536,
) -> bool:
    """
    Baixa um arquivo via streaming informando progresso.
    progress_callback(percent, downloaded_mb, total_mb)
    """
    headers = {"User-Agent": "KnowledgeShip-AutoUpdater"}
    req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req) as resp:
        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with open(dest_path, "wb") as out_file:
            while True:
                if cancel_check and cancel_check():
                    out_file.close()
                    if dest_path.exists():
                        dest_path.unlink(missing_ok=True)
                    return False

                chunk = resp.read(chunk_size)
                if not chunk:
                    break

                out_file.write(chunk)
                downloaded += len(chunk)

                if progress_callback:
                    total_mb = total_size / (1024 * 1024) if total_size > 0 else 0.0
                    downloaded_mb = downloaded / (1024 * 1024)
                    percent = (downloaded / total_size * 100) if total_size > 0 else 0.0
                    progress_callback(percent, downloaded_mb, total_mb)

    return True


def apply_update_and_restart(new_exe_path: Path) -> None:
    """
    Gera um script auxiliar batch em segundo plano que:
    1. Aguarda 1 segundo para o processo atual do Knowledge Ship encerrar completamente e liberar o arquivo.
    2. Sobrescreve o KnowledgeShip.exe atual com a nova versão.
    3. Inicia o novo KnowledgeShip.exe.
    4. Auto-destrói o script batch temporário.
    """
    if getattr(sys, "frozen", False):
        current_exe = Path(sys.executable).resolve()
    else:
        # Modo desenvolvimento
        current_exe = Path(__file__).resolve().parent / "releases" / "KnowledgeShip.exe"

    updater_bat = current_exe.parent / "_updater.bat"
    bat_content = f"""@echo off
setlocal
timeout /t 1 /nobreak >nul
move /y "{new_exe_path.resolve()}" "{current_exe}" >nul
start "" "{current_exe}"
del "%~f0" & exit
"""
    updater_bat.write_text(bat_content, encoding="utf-8")

    # Inicia processo desanexado do Windows sem janela visível
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    subprocess.Popen(
        ["cmd.exe", "/c", str(updater_bat)],
        creationflags=creation_flags,
        close_fds=True,
        cwd=str(current_exe.parent),
    )
