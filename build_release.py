"""
Script de automação de build e gerenciamento de releases do Knowledge Ship.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RELEASES_DIR = BASE_DIR / "releases"


def get_current_version() -> str:
    try:
        import version
        return getattr(version, "__version__", "1.0.0")
    except Exception:
        return "1.0.0"


def set_version(new_version: str):
    version_file = BASE_DIR / "version.py"
    content = f'''"""
Definições de versão e identidade do Knowledge Ship.
"""

__version__ = "{new_version}"
APP_NAME = "Knowledge Ship - Gerenciador de Rotas LLM"
APP_SHORT_NAME = "Knowledge Ship"
APP_DESCRIPTION = "Gerenciador de Rotas, Fallback e Concorrência de Provedores de LLM com API Localhost OpenAI-Compatible"
'''
    version_file.write_text(content, encoding="utf-8")


def main():
    print("=" * 65)
    print("   KNOWLEDGE SHIP - GERENCIADOR DE ROTAS LLM")
    print("   Automacao de Build Portable e Atualizacao de Releases")
    print("=" * 65)
    print()

    current_ver = get_current_version()
    print(f"Versao atual registrada: v{current_ver}")
    print()

    # Verifica argumentos de linha de comando
    target_ver = None
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        target_ver = args[0].strip()
    else:
        try:
            user_input = input(f"Digite a nova versao para este release [Enter para manter {current_ver}]: ").strip()
            if user_input:
                target_ver = user_input
        except EOFError:
            target_ver = current_ver

    if not target_ver:
        target_ver = current_ver

    # Remove prefixo 'v' se digitado
    if target_ver.lower().startswith("v"):
        target_ver = target_ver[1:].strip()

    if target_ver != current_ver:
        print(f"Atualizando version.py para v{target_ver}...")
        set_version(target_ver)
    else:
        print(f"Mantendo versao v{target_ver}...")

    print()
    print("=" * 65)
    print(f"   Iniciando compilacao do release v{target_ver} com PyInstaller...")
    print("=" * 65)
    print()

    # Executa PyInstaller
    spec_path = BASE_DIR / "KnowledgeShip.spec"
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec_path)]
    print(f"Executando: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(BASE_DIR))

    if result.returncode != 0:
        print()
        print("[ERRO] Falha durante a compilacao com PyInstaller.")
        sys.exit(1)

    built_exe = BASE_DIR / "dist" / "KnowledgeShip.exe"
    if not built_exe.exists():
        print()
        print(f"[ERRO] Executavel nao encontrado em {built_exe}")
        sys.exit(1)

    size_mb = built_exe.stat().st_size / (1024 * 1024)
    print(f"\n[OK] Executavel gerado: {built_exe.name} ({size_mb:.2f} MB)")

    # Estrutura a pasta de release
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    version_dir = RELEASES_DIR / f"KnowledgeShip-v{target_ver}"
    version_dir.mkdir(parents=True, exist_ok=True)

    dest_example = version_dir / "config.example.json"
    dest_readme = version_dir / "LEIA-ME.txt"

    # Mantém apenas um único executável no repositório (releases/KnowledgeShip.exe)
    # evitando duplicar 17 MB por versão no histórico do Git
    print(f"Atualizando executável portátil em {RELEASES_DIR / 'KnowledgeShip.exe'}...")
    shutil.copy2(built_exe, RELEASES_DIR / "KnowledgeShip.exe")

    # Copia a pasta assets para releases também
    src_assets = BASE_DIR / "assets"
    dest_assets = RELEASES_DIR / "assets"
    if src_assets.exists():
        if dest_assets.exists():
            shutil.rmtree(dest_assets)
        shutil.copytree(src_assets, dest_assets)

    src_example = BASE_DIR / "config.example.json"
    if src_example.exists():
        shutil.copy2(src_example, dest_example)

    # Cria LEIA-ME.txt
    readme_text = f"""============================================================
 KNOWLEDGE SHIP - GERENCIADOR DE ROTAS LLM
 Versao Portatil: v{target_ver}
============================================================

COMO USAR:
1. O executavel principal e portatil fica em releases/KnowledgeShip.exe.
2. Na primeira execucao, se voce nao tiver um arquivo config.json,
   ele criara automaticamente a partir do config.example.json.
3. Todas as alteracoes salvas na interface grafica serao gravadas
   no config.json do mesmo diretorio do executavel.
4. Voce pode mover o executavel para qualquer computador ou pendrive!

ENDPOINTS DISPONIVEIS APOS INICIAR:
- API Local (OpenAI-compatible): http://localhost:8000/v1/chat/completions
- Lista de Modelos             : http://localhost:8000/v1/models
- Status e Diagnostico         : http://localhost:8000/status
"""
    dest_readme.write_text(readme_text, encoding="utf-8")

    print()
    print("=" * 65)
    print(f"   SUCESSO! RELEASE v{target_ver} GERADO COM EXITO!")
    print("=" * 65)
    print()
    print(f"Executavel mais recente : {RELEASES_DIR / 'KnowledgeShip.exe'}")
    print(f"Pasta da versao         : {version_dir}")
    print()
    print("Arquivos incluidos no pacote portátil:")
    print(f"  - KnowledgeShip.exe ({size_mb:.2f} MB)")
    print("  - config.example.json")
    print("  - LEIA-ME.txt")
    print()


if __name__ == "__main__":
    main()
