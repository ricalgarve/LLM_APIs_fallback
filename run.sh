#!/usr/bin/env bash
# ==============================================================================
# KNOWLEDGE SHIP - GERENCIADOR DE ROTAS LLM (Linux & macOS Launcher)
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "============================================================"
echo "  [KNOWLEDGE SHIP] Gerenciador de Rotas LLM"
echo "  Inicializando no Linux / macOS..."
echo "============================================================"
echo ""

# 1. Verifica ou cria ambiente virtual Python
if [ ! -f ".venv/bin/python" ]; then
    echo "[INFO] Ambiente virtual .venv nao encontrado."
    echo "[INFO] Criando novo ambiente virtual..."
    if command -v python3 >/dev/null 2>&1; then
        python3 -m venv .venv
    elif command -v python >/dev/null 2>&1; then
        python -m venv .venv
    else
        echo "[ERRO] Python 3 nao encontrado! Instale com: sudo apt install python3 python3-venv"
        exit 1
    fi
    echo "[OK] Ambiente virtual criado com sucesso!"
    echo ""
    echo "[INFO] Instalando dependencias do requirements.txt..."
    ./.venv/bin/python -m pip install --upgrade pip --quiet
    ./.venv/bin/python -m pip install -r requirements.txt
    echo ""
fi

# 2. Executa a aplicacao
# Se houver ambiente grafico ($DISPLAY ou $WAYLAND_DISPLAY) e nenhum argumento especifico, abre a GUI.
# Se for servidor sem interface grafica (VPS / SSH / Docker), inicia o servidor FastAPI automaticamente.
if [ "$#" -gt 0 ]; then
    exec ./.venv/bin/python main.py "$@"
elif [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    echo "[INFO] Ambiente grafico detectado. Iniciando Knowledge Ship GUI..."
    exec ./.venv/bin/python gui.py "$@"
else
    echo "[INFO] Nenhum display grafico detectado (modo servidor/headless)."
    echo "[INFO] Iniciando Knowledge Ship em modo servidor FastAPI..."
    exec ./.venv/bin/python main.py --server-only "$@"
fi
