@echo off
setlocal
cd /d "%~dp0"
title Knowledge Ship - Gerenciador de Rotas LLM

echo ============================================================
echo   [KNOWLEDGE SHIP] Gerenciador de Rotas LLM
echo   Inicializando aplicacao...
echo ============================================================
echo.

REM 1. Se o ambiente virtual ja existe, executa diretamente
if exist ".venv\Scripts\python.exe" goto :RUN_APP

echo [INFO] Ambiente virtual .venv nao encontrado.
echo [INFO] Criando novo ambiente virtual...

REM Tenta criar usando o Python Launcher oficial do Windows (py) ou python
py -3 -m venv .venv >nul 2>&1
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv >nul 2>&1
)

if not exist ".venv\Scripts\python.exe" goto :VENV_ERROR

echo [OK] Ambiente virtual criado com sucesso!
echo.
echo [INFO] Instalando dependencias do requirements.txt...
.\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [AVISO] Ocorreu um problema ao instalar dependencias. Tentando prosseguir...
)
echo.

:RUN_APP
REM 2. Inicia a interface grafica utilizando diretamente o Python da venv
echo [INFO] Iniciando Knowledge Ship GUI...
.\.venv\Scripts\python.exe gui.py %*

if errorlevel 1 (
    echo.
    echo [ERRO] A aplicacao foi encerrada com erro.
    pause
)
goto :EOF

:VENV_ERROR
echo.
echo [ERRO] Falha ao criar o ambiente virtual!
echo Verifique se o Python esta instalado no Windows ou disponivel no PATH.
pause
exit /b 1
