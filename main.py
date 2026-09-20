"""
Interface Principal do Barramento de Fallback de LLMs.
Inicia o servidor local OpenAI-compatible e abre a interface de chat interativa no terminal.
"""

import argparse
import asyncio
import sys
import threading
import time
from typing import Optional

import io

# Garante streams válidos mesmo quando compilado com --noconsole no PyInstaller
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Registra App ID explícito no Windows para fixar o ícone náutico na barra de tarefas
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ricalgarve.knowledgeship.1.0")
    except Exception:
        pass

import uvicorn
from config import app_config
from router import router
from server import app
from version import APP_NAME, __version__


import socket

def is_port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

def start_server_in_thread(host: str, port: int) -> Optional[threading.Thread]:
    """Inicia o servidor FastAPI em uma thread separada se a porta não estiver ocupada."""
    if is_port_in_use(host, port):
        return None
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread


def print_banner(host: str, port: int):
    print("\n" + "=" * 70)
    print(f"🚢 {APP_NAME.upper()} (v{__version__})")
    print("=" * 70)
    print(f"📡 API Localhost Ativa  : http://{host}:{port}/v1/chat/completions")
    print(f"📋 Modelos Disponíveis  : http://{host}:{port}/v1/models")
    print(f"🔍 Status e Diagnóstico : http://{host}:{port}/status")
    print(f"⚙️  Modo Atual          : [{app_config.server.mode.upper()}]")
    print("=" * 70)


def print_health_table():
    """Verifica e exibe a tabela de saúde de todos os provedores."""
    print("\n🔍 Verificando integridade das APIs configuradas...")
    results = asyncio.run(router.check_all_health())

    print("\n" + "-" * 70)
    print(f"{'PROVEDOR':<16} | {'MODELO':<28} | {'LATÊNCIA':<9} | {'STATUS'}")
    print("-" * 70)

    for r in results:
        prov = app_config.get_provider(r.provider_id)
        model_name = (prov.model[:25] + "...") if prov and len(prov.model) > 28 else (prov.model if prov else "-")

        if r.status == "online":
            status_tag = f"🟢 ONLINE ({r.latency_ms}ms)"
        elif r.status == "disabled":
            status_tag = "⚪ DESABILITADO"
        elif r.status == "placeholder":
            status_tag = "🟡 SEM CHAVE (config.json)"
        else:
            status_tag = f"🔴 ERRO: {r.error_message or 'Inacessível'}"

        latency = f"{r.latency_ms}ms" if r.latency_ms else "-"
        print(f"{r.name:<16} | {model_name:<28} | {latency:<9} | {status_tag}")

    print("-" * 70 + "\n")


def send_chat_message(prompt: str, stream: bool) -> None:
    """Consome a completion passando pelo roteador de fallback."""
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": "auto",
    }

    try:
        if stream:
            # Consome via streaming do router
            async def _run_stream():
                sse_gen, provider = await router.execute_completion(payload, stream=True)
                print(f"\n[{provider.name} | {provider.model}]:")
                async for chunk in sse_gen:
                    # Chunks chegam no padrão SSE: 'data: {...}\n\n'
                    for line in chunk.splitlines():
                        if line.startswith("data: ") and line.strip() != "data: [DONE]":
                            data_json = line[6:].strip()
                            try:
                                import json
                                parsed = json.loads(data_json)
                                delta = parsed.get("choices", [{}])[0].get("delta", {})
                                token = delta.get("content") or ""
                                if token:
                                    sys.stdout.write(token)
                                    sys.stdout.flush()
                            except Exception:
                                pass
                sys.stdout.write("\n")
                sys.stdout.flush()

            asyncio.run(_run_stream())
        else:
            print("⏳ Aguardando resposta do barramento...")
            async def _run_block():
                res, provider = await router.execute_completion(payload, stream=False)
                print(f"\n[{provider.name} | {provider.model}]:")
                content = res.get("choices", [{}])[0].get("message", {}).get("content", "")
                print(content)

            asyncio.run(_run_block())

    except Exception as e:
        print(f"\n❌ Falha no barramento de fallback: {e}\n")


def run_interactive_cli():
    stream_active = app_config.server.default_stream

    print("Comandos disponíveis:")
    print("  /status ou /check   -> Testa a conexão de todas as APIs")
    print("  /auto               -> Ativa modo de Fallback Automático")
    print("  /use <id>           -> Fixa um provedor específico (ex: /use nvidia ou /use groq)")
    print("  /stream             -> Liga ou desliga o streaming em tempo real")
    print("  sair ou exit        -> Encerra o programa")
    print("=" * 70 + "\n")

    while True:
        try:
            current_mode = app_config.server.mode
            stream_label = "STREAM=ON" if stream_active else "STREAM=OFF"
            user_input = input(f"[{current_mode.upper()} | {stream_label}] Você > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nEncerrando barramento...")
            break

        if not user_input:
            continue

        if user_input.lower() in ("sair", "exit", "quit"):
            print("Encerrando barramento... Até logo!")
            break

        if user_input.lower() in ("/status", "/check"):
            print_health_table()
            continue

        if user_input.lower() == "/auto":
            app_config.set_mode("auto")
            print("🔄 Modo alterado para: FALLBACK AUTOMÁTICO (seleciona primeira API funcional)\n")
            continue

        if user_input.lower().startswith("/use "):
            parts = user_input.split(maxsplit=1)
            if len(parts) > 1:
                target_id = parts[1].strip().lower()
                prov = app_config.get_provider(target_id)
                if prov:
                    app_config.set_mode(target_id)
                    print(f"🔄 Provedor fixado: {prov.name} ({prov.model})\n")
                else:
                    valid_ids = ", ".join(p.id for p in app_config.providers)
                    print(f"❌ Provedor '{target_id}' não existe. Opções válidas: {valid_ids}\n")
            continue

        if user_input.lower() == "/stream":
            stream_active = not stream_active
            status = "LIGADO (tempo real)" if stream_active else "DESLIGADO (bloco único)"
            print(f"🔄 Streaming agora está: {status}\n")
            continue

        send_chat_message(user_input, stream=stream_active)
        print()


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} com Servidor Localhost")
    parser.add_argument("--server-only", action="store_true", help="Executa apenas o servidor FastAPI sem abrir chat interativo.")
    parser.add_argument("--check", action="store_true", help="Verifica a integridade de todos os provedores e sai.")
    parser.add_argument("-p", "--prompt", type=str, default=None, help="Executa um prompt único via barramento e sai.")
    parser.add_argument("--stream", dest="stream", action="store_true", default=None, help="Habilita streaming no prompt único.")
    parser.add_argument("--gui", action="store_true", help="Inicia a interface gráfica Tkinter (padrão se nenhum argumento for fornecido).")
    parser.add_argument("--cli", action="store_true", help="Inicia o chat interativo no terminal em vez da interface gráfica.")

    args = parser.parse_args()

    host = app_config.server.host
    port = app_config.server.port

    if args.check:
        print_health_table()
        sys.exit(0)

    if args.server_only:
        print_banner(host, port)
        print(f"Servidor iniciado em http://{host}:{port} (Pressione Ctrl+C para encerrar)...")
        uvicorn.run(app, host=host, port=port, log_level="info")
        sys.exit(0)

    if args.prompt:
        # Inicia servidor em segundo plano para atender a requisição
        start_server_in_thread(host, port)
        time.sleep(0.5)
        print_banner(host, port)
        stream_choice = app_config.server.default_stream if args.stream is None else args.stream
        send_chat_message(args.prompt, stream=stream_choice)
        sys.exit(0)

    # Se --cli foi solicitado explicitamente, roda modo terminal
    if args.cli:
        start_server_in_thread(host, port)
        time.sleep(0.5)
        print_banner(host, port)
        print_health_table()
        run_interactive_cli()
        sys.exit(0)

    # Padrão: Inicia a interface gráfica moderna Tkinter
    from gui import run_gui
    run_gui()


if __name__ == "__main__":
    main()
