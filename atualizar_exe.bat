@echo off
setlocal
cd /d "%~dp0"
title Knowledge Ship - Compilador e Gerenciador de Releases

set PYTHON_EXE=.\.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

"%PYTHON_EXE%" build_release.py %*

if not "%~1"=="--no-pause" if not "%~2"=="--no-pause" (
    echo Pressione qualquer tecla para sair...
    pause >nul
)
endlocal
