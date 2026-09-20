"""
Interface Gráfica Moderna (Tkinter) para o Barramento de Fallback de LLMs.
Contém:
- Aba 1: Chat Interativo, Streaming e Monitoramento rápido.
- Aba 2: Gerenciamento e Edição Visual de APIs/Provedores (salva no config.json).
- Aba 3: Exposição em Rede Local (0.0.0.0), Bearer Token de Segurança e Gerador de cURL.
"""

import asyncio
import json
import queue
import re
import secrets
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from PIL import Image
import pystray

from config import app_config, ProviderConfig, get_local_ip, generate_bearer_token, parse_headers_input, format_headers_for_display, get_resource_path
from version import __version__, APP_NAME, APP_SHORT_NAME
from router import router, HealthResult, get_provider_endpoint_url
from server import run_server
from bus_logger import bus_logger
import updater
import webbrowser

# ==============================================================================
# TEMA E CORES (Dark Mode Moderno)
# ==============================================================================
BG_DARK = "#181825"
BG_PANEL = "#1e1e2e"
BG_INPUT = "#313244"
FG_TEXT = "#cdd6f4"
FG_SUBTEXT = "#a6adc8"
ACCENT_BLUE = "#89b4fa"
ACCENT_GREEN = "#a6e3a1"
ACCENT_RED = "#f38ba8"
ACCENT_YELLOW = "#f9e2af"
ACCENT_PURPLE = "#cba6f7"
BORDER_COLOR = "#45475a"

FONT_MAIN = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_SUBTITLE = ("Segoe UI", 11, "bold")
FONT_CODE = ("Consolas", 9)


class LLMFallbackGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} v{__version__} - OpenAI Localhost API")
        self.root.geometry("1260x860")
        self.root.minsize(1020, 680)
        self.root.configure(bg=BG_DARK)

        # Ícone Náutico da Janela (Barco)
        self._setup_window_icon()

        self.gui_queue = queue.Queue()
        self.is_generating = False
        self.local_ip = get_local_ip()
        self.current_editing_id: Optional[str] = None
        self.last_sent_prompt: str = ""
        self.last_used_provider_id: Optional[str] = None
        self.provider_health_details: Dict[str, Any] = {}
        self.active_details_modal: Optional[tk.Toplevel] = None
        self.active_details_prov_id: Optional[str] = None

        # Configurações Gerais
        self.var_tray_enabled = tk.BooleanVar(value=getattr(app_config.server, "minimize_to_tray", True))
        self.var_sound_enabled = tk.BooleanVar(value=getattr(app_config.server, "sound_on_request", True))
        self.var_sound_type = tk.StringVar(value=getattr(app_config.server, "sound_type", "water_drop"))
        self.var_toast_enabled = tk.BooleanVar(value=getattr(app_config.server, "show_request_toast", True))
        self.tray_icon = None
        self.active_toast_window: Optional[tk.Toplevel] = None
        self.last_toast_details: Dict[str, Any] = {}

        # Inicia servidor local em thread separada se a porta estiver livre
        self.start_background_server()

        # Estilos e Layout
        self._setup_styles()
        self._build_header()
        self._build_notebook_tabs()

        # Configuração de fechamento e minimização para a bandeja do sistema
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.root.bind("<Unmap>", self._on_window_unmap)
        if self.var_tray_enabled.get():
            self._start_tray_icon()

        # Inscreve listener para receber logs do barramento em tempo real
        bus_logger.subscribe(lambda event: self.gui_queue.put(("bus_log", event)))

        # Agenda processador da fila e health check inicial
        self.root.after(50, self._process_queue)
        self.root.after(400, self.trigger_health_check)
        self.root.after(2000, lambda: self._check_for_updates_interactive(manual=False))

    def start_background_server(self):
        """Inicia o servidor FastAPI local caso ainda não esteja rodando."""
        host = app_config.server.host
        port = app_config.server.port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((host, port)) == 0:
                    return
        except Exception:
            pass
        t = threading.Thread(target=run_server, args=(host, port), daemon=True)
        t.start()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Configuração do Notebook (Abas)
        style.configure("TNotebook", background=BG_DARK, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=BG_PANEL,
            foreground=FG_TEXT,
            padding=[14, 8],
            font=FONT_BOLD,
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", ACCENT_BLUE)],
            foreground=[("selected", "#11111b")],
        )

        # Treeview (tabela de provedores)
        style.configure(
            "Treeview",
            background=BG_INPUT,
            foreground=FG_TEXT,
            fieldbackground=BG_INPUT,
            font=FONT_MAIN,
            rowheight=26,
            borderwidth=0,
        )
        style.configure("Treeview.Heading", background=BG_PANEL, foreground=ACCENT_BLUE, font=FONT_BOLD)
        style.map("Treeview", background=[("selected", ACCENT_BLUE)], foreground=[("selected", "#11111b")])

        # Combobox
        style.configure(
            "TCombobox",
            background=BG_INPUT,
            foreground=FG_TEXT,
            fieldbackground=BG_INPUT,
            darkcolor=BORDER_COLOR,
            lightcolor=BORDER_COLOR,
        )

    def _setup_window_icon(self):
        """Define o ícone náutico (ship) para a janela e barra de tarefas do Windows, substituindo a pena padrão do Tkinter."""
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ricalgarve.knowledgeship.1.0")
            except Exception:
                pass

        ico_applied = False
        for rel in ["assets/ship.ico", "ship.ico"]:
            try:
                ico_path = get_resource_path(rel).resolve()
                if not ico_path.exists():
                    ico_path = (Path(sys.executable).parent / rel).resolve()
                if ico_path.exists():
                    self.root.iconbitmap(default=str(ico_path))
                    self.root.iconbitmap(str(ico_path))
                    ico_applied = True
                    break
            except Exception:
                pass

        if not ico_applied or sys.platform != "win32":
            for rel in ["assets/ship.png", "ship.png"]:
                try:
                    png_path = get_resource_path(rel).resolve()
                    if not png_path.exists():
                        png_path = (Path(sys.executable).parent / rel).resolve()
                    if png_path.exists():
                        self.ship_icon_img = tk.PhotoImage(file=str(png_path))
                        self.root.iconphoto(True, self.ship_icon_img)
                        break
                except Exception:
                    pass

    def _build_header(self):
        header_frame = tk.Frame(self.root, bg=BG_PANEL, height=55, padx=16, pady=8)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        # Banner de Nova Versão (inicia oculto e é empacotado no topo quando há release disponível)
        self.update_banner_frame = tk.Frame(
            self.root,
            bg="#181825",
            padx=16,
            pady=8,
            highlightthickness=1,
            highlightbackground=ACCENT_BLUE,
        )

        title_box = tk.Frame(header_frame, bg=BG_PANEL)
        title_box.pack(side=tk.LEFT)

        title_lbl = tk.Label(
            title_box,
            text=APP_SHORT_NAME,
            font=FONT_TITLE,
            fg=ACCENT_BLUE,
            bg=BG_PANEL,
        )
        title_lbl.pack(side=tk.LEFT)

        sub_lbl = tk.Label(
            title_box,
            text=f" - Gerenciador de Rotas LLM  (v{__version__})",
            font=FONT_SUBTITLE,
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
        )
        sub_lbl.pack(side=tk.LEFT, padx=(4, 0), pady=(3, 0))

        right_box = tk.Frame(header_frame, bg=BG_PANEL)
        right_box.pack(side=tk.RIGHT)

        btn_check_update = tk.Button(
            right_box,
            text="🔄 Checar Atualizações",
            command=lambda: self._check_for_updates_interactive(manual=True),
            font=("Segoe UI", 9),
            fg=ACCENT_BLUE,
            bg=BG_INPUT,
            activebackground="#313244",
            activeforeground=ACCENT_BLUE,
            relief=tk.FLAT,
            padx=8,
            pady=3,
            cursor="hand2",
        )
        btn_check_update.pack(side=tk.RIGHT, padx=(12, 0))

        api_url = f"http://{app_config.server.host}:{app_config.server.port}/v1"
        self.server_status_lbl = tk.Label(
            right_box,
            text=f"🟢 API Ativa: {api_url}",
            font=FONT_BOLD,
            fg=ACCENT_GREEN,
            bg=BG_PANEL,
        )
        self.server_status_lbl.pack(side=tk.RIGHT)

    def _check_for_updates_interactive(self, manual: bool = False):
        """Verifica se há nova versão em background e avisa o usuário."""
        def _worker():
            info = updater.check_for_updates()
            self.root.after(0, lambda: self._on_update_check_finished(info, manual))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_check_finished(self, info: updater.UpdateInfo, manual: bool):
        if info.has_update:
            self._show_update_banner(info)
        elif manual:
            if info.error_message and "404" not in info.error_message:
                messagebox.showwarning("Aviso", f"Não foi possível verificar atualizações no momento:\n{info.error_message}")
            else:
                messagebox.showinfo("Atualizado", f"Você já está utilizando a versão mais recente do Knowledge Ship (v{info.current_version})!")

    def _show_update_banner(self, info: updater.UpdateInfo):
        for w in self.update_banner_frame.winfo_children():
            w.destroy()

        self.update_banner_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(4, 6))

        lbl = tk.Label(
            self.update_banner_frame,
            text=f"🚀 Nova versão disponível: v{info.latest_version}! (Versão atual: v{info.current_version})",
            font=FONT_BOLD,
            fg=ACCENT_YELLOW,
            bg="#181825",
        )
        lbl.pack(side=tk.LEFT)

        btn_box = tk.Frame(self.update_banner_frame, bg="#181825")
        btn_box.pack(side=tk.RIGHT)

        btn_update = tk.Button(
            btn_box,
            text="⚡ Atualizar Agora",
            command=lambda: self._start_update_process(info),
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_GREEN,
            activebackground="#a6e3a1",
            relief=tk.FLAT,
            padx=12,
            pady=3,
            cursor="hand2",
        )
        btn_update.pack(side=tk.LEFT, padx=(0, 8))

        if info.html_url:
            btn_notes = tk.Button(
                btn_box,
                text="🔗 Ver Notas no GitHub",
                command=lambda: webbrowser.open(info.html_url),
                font=FONT_MAIN,
                fg="#11111b",
                bg=ACCENT_BLUE,
                activebackground="#b4befe",
                relief=tk.FLAT,
                padx=8,
                pady=3,
                cursor="hand2",
            )
            btn_notes.pack(side=tk.LEFT, padx=(0, 8))

        btn_close = tk.Button(
            btn_box,
            text="✖ Lembrar Depois",
            command=lambda: self.update_banner_frame.pack_forget(),
            font=FONT_MAIN,
            fg=FG_SUBTEXT,
            bg=BG_INPUT,
            relief=tk.FLAT,
            padx=8,
            pady=3,
            cursor="hand2",
        )
        btn_close.pack(side=tk.LEFT)

    def _start_update_process(self, info: updater.UpdateInfo):
        """Inicia o processo de atualização automática."""
        # Se estiver rodando via Python em desenvolvimento (não compilado)
        if not getattr(sys, "frozen", False):
            msg = (
                f"Uma nova versão (v{info.latest_version}) foi encontrada no GitHub!\n\n"
                "Como você está executando a aplicação a partir do código-fonte Python (.py), "
                "para atualizar execute 'git pull' no terminal ou baixe o release executável."
            )
            if messagebox.askyesno("Atualização Disponível", f"{msg}\n\nDeseja abrir a página do GitHub agora?"):
                webbrowser.open(info.html_url or f"https://github.com/{updater.GITHUB_REPO}/releases")
            return

        # Se não há link de download direto do executável
        if not info.download_url:
            msg = (
                f"A versão v{info.latest_version} foi detectada, mas o arquivo executável "
                "ainda não foi anexado ao release oficial do GitHub.\n\nDeseja abrir a página do GitHub no navegador?"
            )
            if messagebox.askyesno("Aviso", msg):
                webbrowser.open(info.html_url or f"https://github.com/{updater.GITHUB_REPO}/releases")
            return

        # Modal com barra de progresso do download
        dlg = tk.Toplevel(self.root)
        dlg.title(f"Atualizando Knowledge Ship para v{info.latest_version}")
        dlg.geometry("480x210")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.configure(bg=BG_PANEL)

        try:
            dlg.geometry("+%d+%d" % (self.root.winfo_rootx() + 250, self.root.winfo_rooty() + 180))
        except Exception:
            pass

        tk.Label(dlg, text="⬇️ Baixando Nova Versão...", font=FONT_TITLE, fg=ACCENT_BLUE, bg=BG_PANEL).pack(pady=(16, 4))
        lbl_status = tk.Label(dlg, text="Conectando aos servidores do GitHub...", font=FONT_MAIN, fg=FG_TEXT, bg=BG_PANEL)
        lbl_status.pack(pady=(0, 10))

        prog_bar = ttk.Progressbar(dlg, length=420, mode="determinate", maximum=100)
        prog_bar.pack(pady=(0, 8))

        lbl_percent = tk.Label(dlg, text="0%", font=FONT_BOLD, fg=ACCENT_YELLOW, bg=BG_PANEL)
        lbl_percent.pack(pady=(0, 10))

        is_cancelled = False

        def _cancel():
            nonlocal is_cancelled
            is_cancelled = True
            dlg.destroy()

        btn_cancel = tk.Button(dlg, text="Cancelar", command=_cancel, font=FONT_MAIN, fg=FG_TEXT, bg=BG_INPUT, relief=tk.FLAT, padx=12, pady=4, cursor="hand2")
        btn_cancel.pack()

        def _download_worker():
            from pathlib import Path
            target_exe = Path(sys.executable).resolve().parent / "KnowledgeShip_update.exe"

            def _progress(percent, dl_mb, total_mb):
                dlg.after(0, lambda: self._update_download_ui(prog_bar, lbl_status, lbl_percent, percent, dl_mb, total_mb))

            try:
                success = updater.download_file_with_progress(
                    url=info.download_url,
                    dest_path=target_exe,
                    progress_callback=_progress,
                    cancel_check=lambda: is_cancelled,
                )
                if success and not is_cancelled:
                    dlg.after(0, lambda: self._on_download_complete(dlg, lbl_status, btn_cancel, target_exe))
            except Exception as e:
                if not is_cancelled:
                    dlg.after(0, lambda: messagebox.showerror("Erro no Download", f"Falha ao baixar a atualização:\n{e}"))
                    dlg.after(0, dlg.destroy)

        threading.Thread(target=_download_worker, daemon=True).start()

    def _update_download_ui(self, prog_bar, lbl_status, lbl_percent, percent, dl_mb, total_mb):
        prog_bar["value"] = percent
        lbl_percent.config(text=f"{percent:.1f}%")
        if total_mb > 0:
            lbl_status.config(text=f"Baixando: {dl_mb:.2f} MB de {total_mb:.2f} MB")
        else:
            lbl_status.config(text=f"Baixando: {dl_mb:.2f} MB...")

    def _on_download_complete(self, dlg, lbl_status, btn_cancel, target_exe):
        btn_cancel.config(state="disabled")
        lbl_status.config(text="✅ Download concluído! Reiniciando aplicativo...", fg=ACCENT_GREEN)
        self.root.after(1600, lambda: self._apply_and_close(target_exe))

    def _apply_and_close(self, target_exe):
        try:
            updater.apply_update_and_restart(target_exe)
        finally:
            self.root.destroy()
            sys.exit(0)

    def _build_notebook_tabs(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Aba 1: Chat & Monitor
        self.tab_chat = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(self.tab_chat, text="💬 Chat & Monitor")

        # Aba 2: Console de Requisições
        self.tab_console = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(self.tab_console, text="🖥️ Console de Requisições")

        # Aba 3: Configurações de Provedores
        self.tab_providers = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(self.tab_providers, text="⚙️ Configurações de Provedores")

        # Aba 4: Rede & Segurança
        self.tab_network = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(self.tab_network, text="🌐 Rede & Segurança (Bearer Token)")

        # Aba 5: Configurações Gerais
        self.tab_general = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(self.tab_general, text="⚙️ Configurações Gerais")

        self._build_tab_chat(self.tab_chat)
        self._build_tab_console(self.tab_console)
        self._build_tab_providers(self.tab_providers)
        self._build_tab_network(self.tab_network)
        self._build_tab_general(self.tab_general)

    # ==========================================================================
    # ABA 1: CHAT & MONITOR
    # ==========================================================================
    def _build_tab_chat(self, parent):
        content_frame = tk.Frame(parent, bg=BG_DARK)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Painel Esquerdo: Controles rápidos
        left_panel = tk.Frame(content_frame, bg=BG_PANEL, width=420, padx=12, pady=12)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)

        # Painel Direito: Chat
        right_panel = tk.Frame(content_frame, bg=BG_PANEL, padx=12, pady=12)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # --- Controles no painel esquerdo ---
        tk.Label(left_panel, text="⚙️ Modo do Barramento", font=FONT_BOLD, fg=FG_TEXT, bg=BG_PANEL).pack(anchor=tk.W, pady=(0, 6))

        mode_frame = tk.Frame(left_panel, bg=BG_PANEL)
        mode_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(mode_frame, text="Roteamento:", font=FONT_MAIN, fg=FG_SUBTEXT, bg=BG_PANEL).pack(side=tk.LEFT)

        self.mode_var = tk.StringVar(value="auto")
        self.mode_combo = ttk.Combobox(mode_frame, textvariable=self.mode_var, state="readonly", width=22)
        self._update_combo_options()
        self.mode_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(8, 0))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_changed)

        # Checkbox Streaming
        self.stream_var = tk.BooleanVar(value=app_config.server.default_stream)
        tk.Checkbutton(
            left_panel,
            text="⚡ Streaming em tempo real",
            variable=self.stream_var,
            font=FONT_MAIN,
            fg=ACCENT_YELLOW,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            activeforeground=ACCENT_YELLOW,
            selectcolor=BG_INPUT,
            cursor="hand2",
        ).pack(anchor=tk.W, pady=(0, 4))

        # Checkbox Pensamento / Raciocínio
        self.thinking_var = tk.BooleanVar(value=getattr(app_config.server, "show_thinking", True))
        tk.Checkbutton(
            left_panel,
            text="🧠 Exibir Raciocínio (Pensamento)",
            variable=self.thinking_var,
            font=FONT_MAIN,
            fg=ACCENT_PURPLE,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            activeforeground=ACCENT_PURPLE,
            selectcolor=BG_INPUT,
            cursor="hand2",
            command=self._on_thinking_toggled,
        ).pack(anchor=tk.W, pady=(0, 10))

        # Botão Ver Payload & cURL do Provedor Real
        btn_view_payload = tk.Button(
            left_panel,
            text="📦 Ver Payload Real & cURL",
            command=self.show_payload_modal,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_PURPLE,
            activebackground="#b4befe",
            relief=tk.FLAT,
            pady=6,
            cursor="hand2",
        )
        btn_view_payload.pack(fill=tk.X, pady=(0, 6))

        # Botão Copiar cURL do Provedor Real
        btn_copy_curl = tk.Button(
            left_panel,
            text="📋 Copiar cURL (Provedor Real)",
            command=self.copy_curl_to_clipboard,
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_INPUT,
            activebackground=BG_PANEL,
            relief=tk.FLAT,
            pady=4,
            cursor="hand2",
        )
        btn_copy_curl.pack(fill=tk.X, pady=(0, 10))

        # Botão Health Check
        btn_check = tk.Button(
            left_panel,
            text="🔍 Verificar Conexões",
            command=self.trigger_health_check,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_BLUE,
            activebackground="#b4befe",
            relief=tk.FLAT,
            pady=5,
            cursor="hand2",
        )
        btn_check.pack(fill=tk.X, pady=(0, 10))

        # Tabela de status
        tk.Label(left_panel, text="📋 Status dos Provedores & Modelos", font=FONT_BOLD, fg=FG_TEXT, bg=BG_PANEL).pack(anchor=tk.W, pady=(6, 4))
        cols = ("id", "modelo", "latencia", "status")
        self.tree_status = ttk.Treeview(left_panel, columns=cols, show="headings", height=8)
        self.tree_status.heading("id", text="Provedor")
        self.tree_status.heading("modelo", text="Modelo Ativo")
        self.tree_status.heading("latencia", text="Latência")
        self.tree_status.heading("status", text="Status")
        self.tree_status.column("id", width=100, anchor=tk.W)
        self.tree_status.column("modelo", width=145, anchor=tk.W)
        self.tree_status.column("latencia", width=65, anchor=tk.CENTER)
        self.tree_status.column("status", width=85, anchor=tk.W)
        self.tree_status.pack(fill=tk.BOTH, expand=True)

        # Preenche a tabela imediatamente ao abrir a GUI
        self._refresh_status_table()

        # Interações de clique, duplo clique e cursor na tabela de status
        self.tree_status.bind("<ButtonRelease-1>", self._on_status_table_click)
        self.tree_status.bind("<Double-1>", self._on_status_table_double_click)
        self.tree_status.bind("<Motion>", self._on_status_table_motion)

        # Barra de ação rápida para detalhes do status
        status_bar = tk.Frame(left_panel, bg=BG_PANEL)
        status_bar.pack(fill=tk.X, pady=(6, 2))

        self.btn_view_status = tk.Button(
            status_bar,
            text="🔍 Ver Motivo / Detalhes",
            command=self._on_view_selected_status_details,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_BLUE,
            activebackground="#b4befe",
            relief=tk.FLAT,
            pady=4,
            cursor="hand2",
        )
        self.btn_view_status.pack(fill=tk.X)

        tk.Label(
            left_panel,
            text="💡 Dica: Clique no provedor com erro para ver detalhes.",
            font=("Segoe UI", 8),
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
        ).pack(anchor=tk.W, pady=(2, 0))

        # --- Área de Chat no painel direito ---
        top_bar = tk.Frame(right_panel, bg=BG_PANEL)
        top_bar.pack(fill=tk.X, pady=(0, 8))
        tk.Label(top_bar, text="💬 Mensagens", font=FONT_BOLD, fg=FG_TEXT, bg=BG_PANEL).pack(side=tk.LEFT)

        tk.Button(
            top_bar,
            text="Limpar Chat",
            command=self._clear_chat,
            font=FONT_MAIN,
            fg=FG_SUBTEXT,
            bg=BG_INPUT,
            relief=tk.FLAT,
            padx=8,
            pady=2,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        tk.Button(
            top_bar,
            text="📦 Ver Payload Real / cURL",
            command=self.show_payload_modal,
            font=FONT_MAIN,
            fg=ACCENT_PURPLE,
            bg=BG_INPUT,
            relief=tk.FLAT,
            padx=8,
            pady=2,
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(0, 8))

        self.chat_area = scrolledtext.ScrolledText(
            right_panel,
            wrap=tk.WORD,
            bg=BG_DARK,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=FONT_MAIN,
            padx=12,
            pady=12,
            relief=tk.FLAT,
            state=tk.DISABLED,
        )
        self.chat_area.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.chat_area.tag_configure("user_tag", foreground=ACCENT_BLUE, font=FONT_BOLD)
        self.chat_area.tag_configure("bot_tag", foreground=ACCENT_GREEN, font=FONT_BOLD)
        self.chat_area.tag_configure("system_tag", foreground=ACCENT_YELLOW, font=FONT_BOLD)
        self.chat_area.tag_configure("err_tag", foreground=ACCENT_RED, font=FONT_BOLD)
        self.chat_area.tag_configure("thinking_title_tag", foreground=ACCENT_PURPLE, font=FONT_BOLD)
        self.chat_area.tag_configure("thinking_tag", foreground=FG_SUBTEXT, font=("Segoe UI", 9, "italic"))

        input_frame = tk.Frame(right_panel, bg=BG_PANEL)
        input_frame.pack(fill=tk.X)

        self.input_entry = tk.Entry(
            input_frame,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=FONT_MAIN,
            relief=tk.FLAT,
        )
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 8))
        self.input_entry.bind("<Return>", lambda e: self.on_send_message())

        self.btn_send = tk.Button(
            input_frame,
            text="Enviar ➤",
            command=self.on_send_message,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_GREEN,
            activebackground="#a6e3a1",
            relief=tk.FLAT,
            padx=16,
            pady=6,
            cursor="hand2",
        )
        self.btn_send.pack(side=tk.RIGHT)

        self.append_system_msg(f"Barramento ativo. Endpoint local: http://{app_config.server.host}:{app_config.server.port}/v1/chat/completions")

    # ==========================================================================
    # ABA 2: CONSOLE DE REQUISIÇÕES EM TEMPO REAL
    # ==========================================================================
    def _build_tab_console(self, parent):
        content_frame = tk.Frame(parent, bg=BG_DARK)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Barra superior com título e botões de ação
        top_bar = tk.Frame(content_frame, bg=BG_PANEL, padx=12, pady=8)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            top_bar,
            text="🖥️ Monitor em Tempo Real - Requisições /v1/chat/completions",
            font=FONT_BOLD,
            fg=ACCENT_BLUE,
            bg=BG_PANEL,
        ).pack(side=tk.LEFT)

        self.console_autoscroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            top_bar,
            text="Auto-scroll",
            variable=self.console_autoscroll_var,
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            activeforeground=FG_TEXT,
            selectcolor=BG_INPUT,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(20, 0))

        btn_copy_logs = tk.Button(
            top_bar,
            text="📋 Copiar Logs",
            command=self._copy_console_logs,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_PURPLE,
            activebackground="#b4befe",
            relief=tk.FLAT,
            padx=10,
            pady=3,
            cursor="hand2",
        )
        btn_copy_logs.pack(side=tk.RIGHT, padx=(6, 0))

        btn_clear_console = tk.Button(
            top_bar,
            text="🧹 Limpar Console",
            command=self._clear_console,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_RED,
            activebackground="#f38ba8",
            relief=tk.FLAT,
            padx=10,
            pady=3,
            cursor="hand2",
        )
        btn_clear_console.pack(side=tk.RIGHT)

        # Área de log com ScrolledText
        self.console_text = scrolledtext.ScrolledText(
            content_frame,
            wrap=tk.WORD,
            bg="#11111b",
            fg=FG_TEXT,
            insertbackground=ACCENT_BLUE,
            font=("Consolas", 10),
            borderwidth=0,
            padx=10,
            pady=10,
        )
        self.console_text.pack(fill=tk.BOTH, expand=True)

        # Tags com cores do tema
        self.console_text.tag_config("time_tag", foreground=FG_SUBTEXT)
        self.console_text.tag_config("req_tag", foreground="#89dceb", font=("Consolas", 10, "bold"))
        self.console_text.tag_config("attempt_tag", foreground=ACCENT_YELLOW)
        self.console_text.tag_config("stream_tag", foreground=ACCENT_PURPLE)
        self.console_text.tag_config("success_tag", foreground=ACCENT_GREEN, font=("Consolas", 10, "bold"))
        self.console_text.tag_config("error_tag", foreground=ACCENT_RED, font=("Consolas", 10, "bold"))
        self.console_text.tag_config("detail_tag", foreground=FG_TEXT)

        # Carrega histórico prévio gravado pelo bus_logger
        for ev in bus_logger.get_history():
            self._append_console_event(ev)

        self.console_text.config(state=tk.DISABLED)

    def _clear_console(self):
        if hasattr(self, "console_text"):
            self.console_text.config(state=tk.NORMAL)
            self.console_text.delete("1.0", tk.END)
            self.console_text.config(state=tk.DISABLED)

    def _copy_console_logs(self):
        if hasattr(self, "console_text"):
            text = self.console_text.get("1.0", tk.END).strip()
            if text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                messagebox.showinfo("Copiado", "Logs do console copiados com sucesso!")

    def _append_console_event(self, event: dict):
        if not hasattr(self, "console_text"):
            return
        self.console_text.config(state=tk.NORMAL)
        time_str = event.get("timestamp", "")
        level = (event.get("level") or event.get("category") or "INFO").upper()
        message = event.get("message", "")
        details = event.get("details") if event.get("details") is not None else event.get("data", {})

        tag = "detail_tag"
        if level in ("REQ", "REQUEST"):
            tag = "req_tag"
        elif level in ("ATTEMPT", "TRY"):
            tag = "attempt_tag"
        elif level in ("STREAM",):
            tag = "stream_tag"
        elif level in ("SUCCESS", "OK"):
            tag = "success_tag"
        elif level in ("ERROR", "FALLBACK", "WARN"):
            tag = "error_tag"

        self.console_text.insert(tk.END, f"[{time_str}] ", "time_tag")
        self.console_text.insert(tk.END, f"[{level}] ", tag)
        self.console_text.insert(tk.END, f"{message}", tag)

        # Se houver comando cURL nos detalhes, adiciona um link interativo [Detalhes]
        curl_cmd = details.get("curl") if isinstance(details, dict) else None
        if curl_cmd:
            link_tag = f"curl_tag_{id(event)}_{time.time()}_{len(self.console_text.get('1.0', tk.END))}"
            self.console_text.insert(tk.END, "  ")
            self.console_text.insert(tk.END, "[Detalhes]", link_tag)
            self.console_text.tag_config(
                link_tag,
                foreground=ACCENT_BLUE,
                underline=True,
                font=("Consolas", 10, "bold"),
            )
            self.console_text.tag_bind(
                link_tag, "<Enter>", lambda e: self.console_text.config(cursor="hand2")
            )
            self.console_text.tag_bind(
                link_tag, "<Leave>", lambda e: self.console_text.config(cursor="")
            )
            self.console_text.tag_bind(
                link_tag,
                "<Button-1>",
                lambda e, d=details: self.show_curl_modal(d),
            )

        self.console_text.insert(tk.END, "\n")

        if details and isinstance(details, dict):
            for k, v in details.items():
                if k in ("curl", "payload", "provider", "model", "url"):
                    continue
                self.console_text.insert(tk.END, f"      ↳ {k}: {v}\n", "detail_tag")

        if hasattr(self, "console_autoscroll_var") and self.console_autoscroll_var.get():
            self.console_text.see(tk.END)
        self.console_text.config(state=tk.DISABLED)

    # ==========================================================================
    # ABA 3: GERENCIADOR DE PROVEDORES E APIS
    # ==========================================================================
    def _build_tab_providers(self, parent):
        container = tk.Frame(parent, bg=BG_DARK, padx=12, pady=12)
        container.pack(fill=tk.BOTH, expand=True)

        # Lado Esquerdo: Lista de Provedores
        left_box = tk.Frame(container, bg=BG_PANEL, width=320, padx=10, pady=10)
        left_box.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_box.pack_propagate(False)

        tk.Label(left_box, text="Provedores Cadastrados", font=FONT_SUBTITLE, fg=ACCENT_BLUE, bg=BG_PANEL).pack(anchor=tk.W, pady=(0, 8))

        cols = ("name", "enabled")
        self.tree_prov_list = ttk.Treeview(left_box, columns=cols, show="headings", selectmode="browse")
        self.tree_prov_list.heading("name", text="Provedor")
        self.tree_prov_list.heading("enabled", text="Ativo?")
        self.tree_prov_list.column("name", width=190, anchor=tk.W)
        self.tree_prov_list.column("enabled", width=70, anchor=tk.CENTER)
        self.tree_prov_list.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.tree_prov_list.bind("<<TreeviewSelect>>", self._on_provider_selected_in_list)
        self.tree_prov_list.bind("<Double-1>", lambda e: self._toggle_selected_provider_in_list())

        btn_box = tk.Frame(left_box, bg=BG_PANEL)
        btn_box.pack(fill=tk.X)

        tk.Button(
            btn_box,
            text="➕ Novo",
            command=self._on_new_provider_click,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_GREEN,
            relief=tk.FLAT,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        tk.Button(
            btn_box,
            text="🗑️ Excluir",
            command=self._on_delete_provider_click,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_RED,
            relief=tk.FLAT,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(4, 0))

        btn_box2 = tk.Frame(left_box, bg=BG_PANEL)
        btn_box2.pack(fill=tk.X, pady=(6, 0))

        tk.Button(
            btn_box2,
            text="⚡ Ativar / Desativar",
            command=self._toggle_selected_provider_in_list,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_YELLOW,
            activebackground="#f9e2af",
            relief=tk.FLAT,
            padx=6,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        tk.Button(
            btn_box2,
            text="✏️ Renomear",
            command=self._rename_selected_provider_in_list,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_BLUE,
            activebackground="#b4befe",
            relief=tk.FLAT,
            padx=6,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(4, 0))

        # Lado Direito: Formulário de Edição
        right_box = tk.Frame(container, bg=BG_PANEL, padx=16, pady=14)
        right_box.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        tk.Label(right_box, text="📝 Configurações do Provedor Selecionado", font=FONT_SUBTITLE, fg=ACCENT_BLUE, bg=BG_PANEL).pack(anchor=tk.W, pady=(0, 2))
        tk.Label(right_box, text="Edite o nome, ative/desative ou altere chaves e modelos deste provedor:", font=FONT_MAIN, fg=FG_SUBTEXT, bg=BG_PANEL).pack(anchor=tk.W, pady=(0, 8))

        # Botões de Ação do formulário FIXADOS no rodapé do painel (garante 100% de visibilidade sempre)
        action_bar = tk.Frame(right_box, bg=BG_PANEL)
        action_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        tk.Button(
            action_bar,
            text="💾 Salvar Alterações no config.json",
            command=self._save_current_provider,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_GREEN,
            activebackground="#a6e3a1",
            relief=tk.FLAT,
            padx=16,
            pady=8,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        tk.Button(
            action_bar,
            text="🔍 Testar Este Provedor",
            command=self._test_selected_provider,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_BLUE,
            relief=tk.FLAT,
            padx=14,
            pady=8,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(10, 0))

        form_frame = tk.Frame(right_box, bg=BG_PANEL)
        form_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Nome do Provedor (em destaque no topo)
        self.entry_prov_name = self._create_form_field(form_frame, "Nome do Provedor / Nome de Exibição (ex: NVIDIA NIM):", 0)

        # 2. Checkbox Ativar / Desativar
        self.var_prov_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(
            form_frame,
            text="✅ Provedor Ativo (Habilitado no Barramento de Fallback)",
            variable=self.var_prov_enabled,
            font=FONT_BOLD,
            fg=ACCENT_GREEN,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            selectcolor=BG_INPUT,
            cursor="hand2",
        ).grid(row=2, column=0, sticky=tk.W, pady=(3, 8))

        # 3. ID do Provedor
        self.entry_prov_id = self._create_form_field(form_frame, "ID Interno (ex: nvidia, groq):", 2)

        # 4. Base URL
        self.entry_prov_url = self._create_form_field(form_frame, "Base URL do Endpoint (OpenAI-compatible):", 3)

        # 5. URL de Cadastro / Console da API (com botão para abrir no navegador)
        tk.Label(
            form_frame,
            text="🔗 URL de Cadastro / Obtenção de Chave (Console da API):",
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_PANEL,
        ).grid(row=8, column=0, sticky=tk.W, pady=(4, 1))

        signup_frame = tk.Frame(form_frame, bg=BG_PANEL)
        signup_frame.grid(row=9, column=0, sticky="ew", pady=(0, 4))

        self.entry_prov_signup = tk.Entry(
            signup_frame,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=FONT_MAIN,
            relief=tk.FLAT,
        )
        self.entry_prov_signup.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        btn_open_signup = tk.Button(
            signup_frame,
            text="🌐 Abrir no Navegador",
            command=self._open_provider_signup_url,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_YELLOW,
            activebackground="#f9e2af",
            relief=tk.FLAT,
            padx=8,
            cursor="hand2",
        )
        btn_open_signup.pack(side=tk.RIGHT, padx=(6, 0))

        # 6. API Key com botão de exibir/ocultar
        tk.Label(form_frame, text="API Key / Token:", font=FONT_MAIN, fg=FG_TEXT, bg=BG_PANEL).grid(row=10, column=0, sticky=tk.W, pady=(4, 1))
        key_frame = tk.Frame(form_frame, bg=BG_PANEL)
        key_frame.grid(row=11, column=0, sticky="ew", pady=(0, 4))
        form_frame.columnconfigure(0, weight=1)

        self.entry_prov_key = tk.Entry(key_frame, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, font=FONT_MAIN, relief=tk.FLAT, show="•")
        self.entry_prov_key.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        self.btn_toggle_eye = tk.Button(
            key_frame,
            text="👁️",
            command=self._toggle_api_key_visibility,
            bg=BG_INPUT,
            fg=FG_TEXT,
            relief=tk.FLAT,
            padx=6,
            cursor="hand2",
        )
        self.btn_toggle_eye.pack(side=tk.RIGHT, padx=(4, 0))

        # 7. Modelos do Provedor (Seletor Combobox + Adicionar / Remover)
        tk.Label(
            form_frame,
            text="🤖 Modelo Ativo (Selecione da lista ou digite para adicionar):",
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_PANEL,
        ).grid(row=12, column=0, sticky=tk.W, pady=(4, 1))

        model_row = tk.Frame(form_frame, bg=BG_PANEL)
        model_row.grid(row=13, column=0, sticky="ew", pady=(0, 4))

        self.combo_prov_model = ttk.Combobox(model_row, font=FONT_MAIN, state="normal")
        self.combo_prov_model.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)

        btn_add_model = tk.Button(
            model_row,
            text="➕ Adicionar à Lista",
            command=self._on_add_model_to_provider,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_BLUE,
            activebackground="#b4befe",
            relief=tk.FLAT,
            padx=8,
            pady=3,
            cursor="hand2",
        )
        btn_add_model.pack(side=tk.LEFT, padx=(6, 4))

        btn_del_model = tk.Button(
            model_row,
            text="🗑️ Remover",
            command=self._on_remove_model_from_provider,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_RED,
            activebackground="#f38ba8",
            relief=tk.FLAT,
            padx=8,
            pady=3,
            cursor="hand2",
        )
        btn_del_model.pack(side=tk.LEFT)

        # 8. Headers HTTP Customizados (ex: Api-Revision, x-goog-api-key)
        tk.Label(
            form_frame,
            text="🌐 Headers HTTP Customizados (um por linha 'Header: Valor', JSON ou flags cURL):",
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_PANEL,
        ).grid(row=14, column=0, sticky=tk.W, pady=(4, 1))

        self.text_prov_headers = tk.Text(
            form_frame,
            height=2,
            font=FONT_CODE,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief=tk.FLAT,
            padx=8,
            pady=4,
        )
        self.text_prov_headers.grid(row=15, column=0, sticky="ew", pady=(0, 2))

        lbl_hint_headers = tk.Label(
            form_frame,
            text="Ex: Api-Revision: 2026-05-20  |  x-goog-api-key: SUA_CHAVE  |  HTTP-Referer: https://meusite.com",
            font=("Segoe UI", 8),
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
        )
        lbl_hint_headers.grid(row=16, column=0, sticky=tk.W, pady=(0, 4))

        self._refresh_providers_list()

    def _create_form_field(self, parent, label_text: str, row: int) -> tk.Entry:
        tk.Label(parent, text=label_text, font=FONT_MAIN, fg=FG_TEXT, bg=BG_PANEL).grid(row=row*2, column=0, sticky=tk.W, pady=(4, 1))
        entry = tk.Entry(parent, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, font=FONT_MAIN, relief=tk.FLAT)
        entry.grid(row=row*2+1, column=0, sticky="ew", pady=(0, 4), ipady=4)
        return entry

    def _open_provider_signup_url(self):
        url = self.entry_prov_signup.get().strip()
        if not url:
            messagebox.showinfo("Aviso", "Nenhuma URL de cadastro/console informada para este provedor.")
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        import webbrowser
        webbrowser.open(url)

    def _toggle_api_key_visibility(self):
        if self.entry_prov_key.cget("show") == "":
            self.entry_prov_key.config(show="•")
        else:
            self.entry_prov_key.config(show="")

    def _refresh_providers_list(self):
        """Atualiza a lista visual de provedores."""
        for item in self.tree_prov_list.get_children():
            self.tree_prov_list.delete(item)

        for p in app_config.providers:
            status_txt = "Sim" if p.enabled else "Não"
            if not self.tree_prov_list.exists(p.id):
                self.tree_prov_list.insert("", tk.END, iid=p.id, values=(p.name, status_txt))

        # Mantém a seleção do provedor atual ou seleciona o primeiro por padrão
        target_id = None
        if self.current_editing_id and self.tree_prov_list.exists(self.current_editing_id):
            target_id = self.current_editing_id
        elif app_config.providers:
            target_id = app_config.providers[0].id

        if target_id and self.tree_prov_list.exists(target_id):
            self.tree_prov_list.selection_set(target_id)
            self._load_provider_into_form(target_id)

    def _on_provider_selected_in_list(self, event=None):
        selected = self.tree_prov_list.selection()
        if selected:
            prov_id = selected[0]
            self._load_provider_into_form(prov_id)

    def _load_provider_into_form(self, provider_id: str):
        p = app_config.get_provider(provider_id)
        if not p:
            return
        self.current_editing_id = provider_id
        self.entry_prov_id.delete(0, tk.END)
        self.entry_prov_id.insert(0, p.id)
        self.entry_prov_name.delete(0, tk.END)
        self.entry_prov_name.insert(0, p.name)
        self.entry_prov_url.delete(0, tk.END)
        self.entry_prov_url.insert(0, p.base_url)
        self.entry_prov_signup.delete(0, tk.END)
        self.entry_prov_signup.insert(0, getattr(p, "signup_url", "") or "")
        self.entry_prov_key.delete(0, tk.END)
        self.entry_prov_key.insert(0, p.api_key)
        models = getattr(p, "models", []) or ([p.model] if p.model else [])
        self.combo_prov_model["values"] = models
        self.combo_prov_model.set(p.model)
        self.var_prov_enabled.set(p.enabled)
        headers = getattr(p, "headers", {}) or {}
        self.text_prov_headers.delete("1.0", tk.END)
        if headers:
            self.text_prov_headers.insert("1.0", format_headers_for_display(headers))

    def _on_new_provider_click(self):
        self.current_editing_id = None
        self.entry_prov_id.delete(0, tk.END)
        self.entry_prov_id.insert(0, f"novo_{len(app_config.providers)+1}")
        self.entry_prov_name.delete(0, tk.END)
        self.entry_prov_name.insert(0, "Novo Provedor")
        self.entry_prov_url.delete(0, tk.END)
        self.entry_prov_url.insert(0, "https://api.exemplo.com/v1")
        self.entry_prov_signup.delete(0, tk.END)
        self.entry_prov_signup.insert(0, "https://console.exemplo.com/keys")
        self.entry_prov_key.delete(0, tk.END)
        self.text_prov_headers.delete("1.0", tk.END)
        self.combo_prov_model["values"] = ["modelo-exemplo-1", "modelo-exemplo-2"]
        self.combo_prov_model.set("modelo-exemplo-1")
        self.var_prov_enabled.set(True)

    def _on_add_model_to_provider(self):
        new_m = self.combo_prov_model.get().strip()
        if not new_m:
            messagebox.showwarning("Aviso", "Digite o nome do modelo no campo antes de adicionar.")
            return
        vals = list(self.combo_prov_model["values"])
        if new_m not in vals:
            vals.append(new_m)
            self.combo_prov_model["values"] = vals
            self.combo_prov_model.set(new_m)
            messagebox.showinfo("Adicionado", f"Modelo '{new_m}' adicionado à lista deste provedor. Clique em 'Salvar Alterações' para gravar.")
        else:
            messagebox.showinfo("Informação", f"O modelo '{new_m}' já está na lista deste provedor.")

    def _on_remove_model_from_provider(self):
        current_m = self.combo_prov_model.get().strip()
        vals = list(self.combo_prov_model["values"])
        if not current_m or current_m not in vals:
            messagebox.showwarning("Aviso", "Selecione um modelo da lista para remover.")
            return
        if len(vals) <= 1:
            messagebox.showwarning("Aviso", "O provedor deve ter ao menos um modelo na lista.")
            return
        if messagebox.askyesno("Confirmar", f"Deseja remover o modelo '{current_m}' da lista deste provedor?"):
            vals.remove(current_m)
            self.combo_prov_model["values"] = vals
            self.combo_prov_model.set(vals[0])
            messagebox.showinfo("Removido", f"Modelo '{current_m}' removido da lista. Clique em 'Salvar Alterações' para gravar.")

    def _on_delete_provider_click(self):
        selected = self.tree_prov_list.selection()
        if not selected:
            messagebox.showwarning("Aviso", "Selecione um provedor para excluir.")
            return
        prov_id = selected[0]
        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o provedor '{prov_id}'?"):
            app_config.delete_provider(prov_id)
            self._refresh_providers_list()
            self._update_combo_options()
            self.trigger_health_check()
            messagebox.showinfo("Sucesso", f"Provedor '{prov_id}' removido!")

    def _toggle_selected_provider_in_list(self):
        """Ativa ou desativa o provedor selecionado na lista."""
        selected = self.tree_prov_list.selection()
        if not selected:
            messagebox.showwarning("Aviso", "Selecione um provedor na lista para ativar ou desativar.")
            return
        prov_id = selected[0]
        new_state = app_config.toggle_provider(prov_id)
        if new_state is not None:
            self._refresh_providers_list()
            self._update_combo_options()
            if self.current_editing_id == prov_id:
                self.var_prov_enabled.set(new_state)
            self.trigger_health_check()
            st_text = "ATIVADO" if new_state else "DESATIVADO"
            p = app_config.get_provider(prov_id)
            self.append_system_msg(f"Provedor '{p.name if p else prov_id}' foi {st_text}.")

    def _rename_selected_provider_in_list(self):
        """Permite renomear o nome amigável do provedor selecionado rapidamente."""
        selected = self.tree_prov_list.selection()
        if not selected:
            messagebox.showwarning("Aviso", "Selecione um provedor na lista para renomear.")
            return
        prov_id = selected[0]
        p = app_config.get_provider(prov_id)
        if not p:
            return
        new_name = simpledialog.askstring(
            "Renomear Provedor",
            f"Digite o novo nome para '{p.name}':",
            initialvalue=p.name,
            parent=self.root,
        )
        if new_name and new_name.strip():
            app_config.rename_provider(prov_id, new_name.strip())
            self._refresh_providers_list()
            self._update_combo_options()
            if self.current_editing_id == prov_id:
                self.entry_prov_name.delete(0, tk.END)
                self.entry_prov_name.insert(0, new_name.strip())
            self.trigger_health_check()
            self.append_system_msg(f"Provedor renomeado para '{new_name.strip()}'.")

    def _save_current_provider(self):
        pid = self.entry_prov_id.get().strip().lower()
        name = self.entry_prov_name.get().strip()
        url = self.entry_prov_url.get().strip()
        signup_url = self.entry_prov_signup.get().strip()
        key = self.entry_prov_key.get().strip()
        selected_model = self.combo_prov_model.get().strip()
        enabled = self.var_prov_enabled.get()

        if not pid or not name or not url or not selected_model:
            messagebox.showerror("Erro", "ID, Nome, Base URL e Modelo são campos obrigatórios.")
            return

        models = list(self.combo_prov_model["values"])
        if selected_model not in models:
            models.append(selected_model)

        headers_raw = self.text_prov_headers.get("1.0", tk.END).strip()
        headers = parse_headers_input(headers_raw)

        new_p = ProviderConfig(
            id=pid,
            name=name,
            base_url=url,
            api_key=key,
            model=selected_model,
            models=models,
            enabled=enabled,
            headers=headers,
            signup_url=signup_url,
        )
        app_config.upsert_provider(new_p, old_id=self.current_editing_id)
        self.current_editing_id = pid
        self._refresh_providers_list()
        self._update_combo_options()
        self.trigger_health_check()
        messagebox.showinfo("Sucesso", f"Provedor '{name}' salvo com sucesso com o modelo '{selected_model}'!")

    def _test_selected_provider(self):
        pid = self.entry_prov_id.get().strip()
        p = app_config.get_provider(pid)
        if not p:
            messagebox.showwarning("Aviso", "Salve o provedor antes de testar.")
            return

        current_model = self.combo_prov_model.get().strip() or p.model
        headers_raw = self.text_prov_headers.get("1.0", tk.END).strip()
        current_headers = parse_headers_input(headers_raw) if headers_raw else (getattr(p, "headers", {}) or {})
        current_key = self.entry_prov_key.get().strip() or p.api_key

        def _test_worker():
            test_p = ProviderConfig(
                id=p.id,
                name=p.name,
                base_url=p.base_url,
                api_key=current_key,
                model=current_model,
                models=getattr(p, "models", []),
                enabled=p.enabled,
                headers=current_headers,
                signup_url=getattr(p, "signup_url", ""),
            )
            res = asyncio.run(router.check_provider_health(test_p))
            self.gui_queue.put(("health_single_result", res))
            if res.status == "online":
                msg = f"🟢 Provedor ONLINE!\nLatência: {res.latency_ms}ms\nModelo testado: {current_model}"
                self.root.after(0, lambda: messagebox.showinfo("Teste Concluído", msg))
            else:
                msg = f"🔴 Provedor com FALHA!\nStatus: {res.status}\nModelo testado: {current_model}\nDetalhes: {res.error_message}"
                self.root.after(0, lambda: messagebox.showerror("Falha no Teste", msg))

        threading.Thread(target=_test_worker, daemon=True).start()

    # ==========================================================================
    # ABA 3: REDE & SEGURANÇA (BEARER TOKEN & CURL)
    # ==========================================================================
    def _build_tab_network(self, parent):
        container = tk.Frame(parent, bg=BG_DARK, padx=16, pady=16)
        container.pack(fill=tk.BOTH, expand=True)

        # Seção 1: Configuração de Exposição de Rede
        sec_net = tk.LabelFrame(container, text=" 🌐 Exposição de Rede (Host & Porta) ", font=FONT_SUBTITLE, fg=ACCENT_BLUE, bg=BG_PANEL, padx=14, pady=12)
        sec_net.pack(fill=tk.X, pady=(0, 14))

        self.var_network_mode = tk.StringVar(value="lan" if app_config.server.host == "0.0.0.0" else "localhost")

        tk.Radiobutton(
            sec_net,
            text="Apenas nesta máquina (Localhost - 127.0.0.1)",
            variable=self.var_network_mode,
            value="localhost",
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            selectcolor=BG_INPUT,
            cursor="hand2",
            command=self._on_network_mode_changed,
        ).pack(anchor=tk.W, pady=(0, 4))

        tk.Radiobutton(
            sec_net,
            text=f"Liberar para toda a rede local (0.0.0.0) -> Acessível por outros dispositivos via http://{self.local_ip}:{app_config.server.port}",
            variable=self.var_network_mode,
            value="lan",
            font=FONT_MAIN,
            fg=ACCENT_GREEN,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            selectcolor=BG_INPUT,
            cursor="hand2",
            command=self._on_network_mode_changed,
        ).pack(anchor=tk.W, pady=(0, 8))

        # Seção 2: Bearer Token de Segurança
        sec_sec = tk.LabelFrame(container, text=" 🔒 Segurança & Autenticação (Bearer Token) ", font=FONT_SUBTITLE, fg=ACCENT_YELLOW, bg=BG_PANEL, padx=14, pady=12)
        sec_sec.pack(fill=tk.X, pady=(0, 14))

        self.var_require_auth = tk.BooleanVar(value=app_config.server.require_auth)
        tk.Checkbutton(
            sec_sec,
            text="Exigir Bearer Token para aceitar requisições na API",
            variable=self.var_require_auth,
            font=FONT_BOLD,
            fg=ACCENT_YELLOW,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            selectcolor=BG_INPUT,
            cursor="hand2",
            command=self._on_auth_changed,
        ).pack(anchor=tk.W, pady=(0, 8))

        token_box = tk.Frame(sec_sec, bg=BG_PANEL)
        token_box.pack(fill=tk.X, pady=(0, 8))

        tk.Label(token_box, text="Bearer Token:", font=FONT_MAIN, fg=FG_SUBTEXT, bg=BG_PANEL).pack(side=tk.LEFT)
        self.entry_token = tk.Entry(token_box, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, font=FONT_MAIN, relief=tk.FLAT)
        self.entry_token.insert(0, app_config.server.auth_token)
        self.entry_token.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8), ipady=4)

        tk.Button(
            token_box,
            text="🎲 Gerar Novo Token",
            command=self._on_generate_token_click,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_BLUE,
            relief=tk.FLAT,
            padx=8,
            pady=3,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(
            token_box,
            text="💾 Salvar",
            command=self._on_save_network_security,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_GREEN,
            relief=tk.FLAT,
            padx=10,
            pady=3,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        # Seção 3: Visualizador do comando cURL
        sec_curl = tk.LabelFrame(container, text=" 📋 Comando cURL Completo ", font=FONT_SUBTITLE, fg=ACCENT_PURPLE, bg=BG_PANEL, padx=14, pady=12)
        sec_curl.pack(fill=tk.BOTH, expand=True)

        self.text_curl_preview = tk.Text(sec_curl, height=6, bg=BG_DARK, fg=FG_TEXT, font=FONT_CODE, relief=tk.FLAT, wrap=tk.NONE)
        self.text_curl_preview.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        btn_copy_bar = tk.Frame(sec_curl, bg=BG_PANEL)
        btn_copy_bar.pack(fill=tk.X)

        tk.Button(
            btn_copy_bar,
            text="📋 Copiar cURL para Área de Transferência",
            command=self.copy_curl_to_clipboard,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_PURPLE,
            relief=tk.FLAT,
            padx=14,
            pady=6,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        self._update_curl_preview()

    # ==========================================================================
    # ABA 5: CONFIGURAÇÕES GERAIS (Tray Icon, Notificações Sonoras & HUD Toast)
    # ==========================================================================
    def _build_tab_general(self, parent):
        container = tk.Frame(parent, bg=BG_DARK, padx=16, pady=16)
        container.pack(fill=tk.BOTH, expand=True)

        # Seção 1: Bandeja do Sistema (System Tray)
        sec_tray = tk.LabelFrame(
            container,
            text=" 🚢 Bandeja do Sistema (System Tray Icon) ",
            font=FONT_SUBTITLE,
            fg=ACCENT_BLUE,
            bg=BG_PANEL,
            padx=14,
            pady=12,
        )
        sec_tray.pack(fill=tk.X, pady=(0, 14))

        tk.Checkbutton(
            sec_tray,
            text="Habilitar ícone na bandeja do sistema (System Tray)",
            variable=self.var_tray_enabled,
            font=FONT_BOLD,
            fg=FG_TEXT,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            activeforeground=FG_TEXT,
            selectcolor=BG_INPUT,
            cursor="hand2",
            command=self._on_tray_toggle,
        ).pack(anchor=tk.W, pady=(0, 4))

        tk.Label(
            sec_tray,
            text="Quando ativado, minimizar ou fechar a janela ocultará o aplicativo para a bandeja ao lado do relógio do Windows.\n"
                 "Dê um clique duplo ou clique com o botão direito no ícone do navio para restaurar ou encerrar a aplicação.",
            font=FONT_MAIN,
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 10))

        btn_tray_bar = tk.Frame(sec_tray, bg=BG_PANEL)
        btn_tray_bar.pack(fill=tk.X)

        tk.Button(
            btn_tray_bar,
            text="⬇️ Minimizar Agora para a Bandeja",
            command=self._minimize_to_tray_now,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_BLUE,
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        # Seção 2: Notificações Sonoras
        sec_sound = tk.LabelFrame(
            container,
            text=" 🔊 Notificações Sonoras (Áudio) ",
            font=FONT_SUBTITLE,
            fg=ACCENT_YELLOW,
            bg=BG_PANEL,
            padx=14,
            pady=12,
        )
        sec_sound.pack(fill=tk.X, pady=(0, 14))

        tk.Checkbutton(
            sec_sound,
            text="Disparar som ao receber requisição no barramento (/v1/chat/completions)",
            variable=self.var_sound_enabled,
            font=FONT_BOLD,
            fg=ACCENT_YELLOW,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            activeforeground=ACCENT_YELLOW,
            selectcolor=BG_INPUT,
            cursor="hand2",
            command=self._save_general_settings,
        ).pack(anchor=tk.W, pady=(0, 4))

        sound_choice_frame = tk.Frame(sec_sound, bg=BG_PANEL)
        sound_choice_frame.pack(fill=tk.X, pady=(4, 6))

        tk.Label(sound_choice_frame, text="Efeito Sonoro:", font=FONT_MAIN, fg=FG_TEXT, bg=BG_PANEL).pack(side=tk.LEFT, padx=(0, 10))

        sound_options = [
            ("💧 Gota d'Água na Água (Recomendado)", "water_drop"),
            ("🔔 Beep / Sino Padrão do Windows", "beep"),
        ]

        val_to_label = {v: l for l, v in sound_options}
        label_to_val = {l: v for l, v in sound_options}
        current_val = self.var_sound_type.get()

        self.sound_display_var = tk.StringVar(value=val_to_label.get(current_val, "💧 Gota d'Água na Água (Recomendado)"))

        def _on_sound_type_select(event=None):
            sel_label = self.sound_display_var.get()
            self.var_sound_type.set(label_to_val.get(sel_label, "water_drop"))
            self._save_general_settings()
            self._test_sound()

        combo_sound = ttk.Combobox(
            sound_choice_frame,
            textvariable=self.sound_display_var,
            values=[l for l, _ in sound_options],
            state="readonly",
            width=36,
        )
        combo_sound.pack(side=tk.LEFT)
        combo_sound.bind("<<ComboboxSelected>>", _on_sound_type_select)

        tk.Label(
            sec_sound,
            text="Toca um efeito sonoro suave e acústico toda vez que uma nova requisição chegar ao barramento.",
            font=FONT_MAIN,
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 10))

        btn_sound_bar = tk.Frame(sec_sound, bg=BG_PANEL)
        btn_sound_bar.pack(fill=tk.X)

        tk.Button(
            btn_sound_bar,
            text="🔊 Testar Som de Requisição",
            command=self._test_sound,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_YELLOW,
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        # Seção 3: Notificação Flutuante (Toast HUD)
        sec_toast = tk.LabelFrame(
            container,
            text=" 🪟 Notificação Flutuante de Requisições (Toast HUD no Canto da Tela) ",
            font=FONT_SUBTITLE,
            fg=ACCENT_GREEN,
            bg=BG_PANEL,
            padx=14,
            pady=12,
        )
        sec_toast.pack(fill=tk.X, pady=(0, 14))

        tk.Checkbutton(
            sec_toast,
            text="Exibir card flutuante com tokens e links de inspeção ao concluir cada requisição",
            variable=self.var_toast_enabled,
            font=FONT_BOLD,
            fg=ACCENT_GREEN,
            bg=BG_PANEL,
            activebackground=BG_PANEL,
            activeforeground=ACCENT_GREEN,
            selectcolor=BG_INPUT,
            cursor="hand2",
            command=self._save_general_settings,
        ).pack(anchor=tk.W, pady=(0, 4))

        tk.Label(
            sec_toast,
            text="Exibe uma notificação flutuante elegante no canto inferior direito da tela com tempo de resposta,\n"
                 "total de tokens utilizados (Prompt + Resposta) e dois links diretos para visualizar o Prompt enviado e a Resposta do provedor.",
            font=FONT_MAIN,
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 10))

        btn_toast_bar = tk.Frame(sec_toast, bg=BG_PANEL)
        btn_toast_bar.pack(fill=tk.X)

        tk.Button(
            btn_toast_bar,
            text="🪟 Testar Notificação Flutuante",
            command=self._test_toast,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_GREEN,
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        # Rodapé com Botão Salvar
        bottom_bar = tk.Frame(container, bg=BG_DARK, pady=10)
        bottom_bar.pack(fill=tk.X)

        tk.Button(
            bottom_bar,
            text="💾 Salvar Configurações Gerais",
            command=self._save_general_settings,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_BLUE,
            relief=tk.FLAT,
            padx=16,
            pady=6,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        self.lbl_general_status = tk.Label(bottom_bar, text="", font=FONT_BOLD, fg=ACCENT_GREEN, bg=BG_DARK)
        self.lbl_general_status.pack(side=tk.LEFT, padx=(12, 0))

    def _save_general_settings(self):
        app_config.server.minimize_to_tray = bool(self.var_tray_enabled.get())
        app_config.server.sound_on_request = bool(self.var_sound_enabled.get())
        app_config.server.sound_type = str(self.var_sound_type.get())
        app_config.server.show_request_toast = bool(self.var_toast_enabled.get())
        app_config.save()
        if hasattr(self, "lbl_general_status"):
            self.lbl_general_status.config(text="✅ Configurações salvas com sucesso!", fg=ACCENT_GREEN)
            self.root.after(3000, lambda: self.lbl_general_status.config(text="") if hasattr(self, "lbl_general_status") else None)

    def _on_tray_toggle(self):
        self._save_general_settings()
        if self.var_tray_enabled.get():
            self._start_tray_icon()
        else:
            self._stop_tray_icon()

    def _start_tray_icon(self):
        if self.tray_icon is not None:
            return

        def _restore_action(icon=None, item=None):
            self.root.after(0, self._restore_from_tray)

        def _quit_action(icon=None, item=None):
            self.root.after(0, self._quit_application)

        def _minimize_action(icon=None, item=None):
            self.root.after(0, self._minimize_to_tray_now)

        try:
            img = None
            for rel in ["assets/ship.png", "ship.png"]:
                p = get_resource_path(rel).resolve()
                if not p.exists():
                    p = (Path(sys.executable).parent / rel).resolve()
                if p.exists():
                    img = Image.open(str(p))
                    break

            if img is None:
                img = Image.new("RGBA", (64, 64), color=(137, 180, 250, 255))

            menu = pystray.Menu(
                pystray.MenuItem("Abrir Knowledge Ship", _restore_action, default=True),
                pystray.MenuItem("Minimizar para a Bandeja", _minimize_action),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Sair", _quit_action),
            )

            self.tray_icon = pystray.Icon(
                "KnowledgeShip",
                img,
                f"{APP_NAME} v{__version__}",
                menu,
            )
            self.tray_icon.run_detached()
        except Exception as e:
            print(f"[AVISO] Falha ao inicializar Tray Icon: {e}")
            self.tray_icon = None

    def _stop_tray_icon(self):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None

    def _on_window_close(self):
        if self.var_tray_enabled.get():
            self._minimize_to_tray_now()
        else:
            self._quit_application()

    def _on_window_unmap(self, event):
        if event.widget == self.root:
            if self.root.state() == "iconic" and self.var_tray_enabled.get():
                self._minimize_to_tray_now()

    def _minimize_to_tray_now(self):
        if not self.tray_icon:
            self._start_tray_icon()
        self.root.withdraw()

    def _restore_from_tray(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def _quit_application(self):
        self._stop_tray_icon()
        self.root.destroy()
        sys.exit(0)

    def _play_request_sound(self):
        if not self.var_sound_enabled.get():
            return
        sound_type = self.var_sound_type.get() if hasattr(self, "var_sound_type") else getattr(app_config.server, "sound_type", "water_drop")

        def _play():
            if sys.platform == "win32":
                try:
                    import winsound
                    if sound_type == "water_drop":
                        wav_path = get_resource_path("assets/water_drop.wav").resolve()
                        if not wav_path.exists():
                            wav_path = (Path(sys.executable).parent / "assets" / "water_drop.wav").resolve()
                        if wav_path.exists():
                            winsound.PlaySound(str(wav_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
                            return
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                except Exception:
                    pass
            elif sys.platform.startswith("linux") or sys.platform == "darwin":
                try:
                    import shutil
                    import subprocess
                    wav_path = get_resource_path("assets/water_drop.wav").resolve()
                    if not wav_path.exists():
                        wav_path = (Path(sys.executable).parent / "assets" / "water_drop.wav").resolve()

                    if sound_type == "water_drop" and wav_path.exists():
                        for player in ["afplay", "paplay", "pw-play", "aplay", "canberra-gtk-play"]:
                            if shutil.which(player):
                                if player == "canberra-gtk-play":
                                    subprocess.Popen([player, "-f", str(wav_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                else:
                                    subprocess.Popen([player, str(wav_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                return

                    # Fallback sonoro de terminal
                    sys.stdout.write("\a")
                    sys.stdout.flush()
                except Exception:
                    pass
        threading.Thread(target=_play, daemon=True).start()

    def _test_sound(self):
        self._play_request_sound()

    def _on_request_received(self, data: Dict[str, Any]):
        self._play_request_sound()

    def _on_completion_finished(self, data: Dict[str, Any]):
        details = data.get("details") or {}
        self._show_request_toast(details)

    def _close_toast(self, toast=None):
        target = toast or self.active_toast_window
        if target:
            try:
                target.destroy()
            except Exception:
                pass
        if target == self.active_toast_window:
            self.active_toast_window = None

    def _show_request_toast(self, details: Dict[str, Any]):
        if not self.var_toast_enabled.get():
            return

        self._close_toast()

        toast = tk.Toplevel(self.root)
        self.active_toast_window = toast
        self.last_toast_details = dict(details)

        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=BG_PANEL, highlightthickness=1, highlightbackground=ACCENT_BLUE)

        prov_name = details.get("provider", "Provedor LLM")
        model = details.get("model", "auto")
        lat_ms = details.get("latency_ms", 0)
        usage = details.get("usage") or {}
        p_tokens = usage.get("prompt_tokens", 0)
        c_tokens = usage.get("completion_tokens", 0)
        t_tokens = usage.get("total_tokens", p_tokens + c_tokens)

        # Barra de título do toast
        hdr = tk.Frame(toast, bg="#181825", padx=8, pady=5)
        hdr.pack(fill=tk.X)

        tk.Label(hdr, text="🚢 Knowledge Ship", font=FONT_BOLD, fg=ACCENT_BLUE, bg="#181825").pack(side=tk.LEFT)
        tk.Label(hdr, text=f"⚡ {lat_ms}ms", font=("Segoe UI", 9, "bold"), fg=ACCENT_GREEN, bg="#181825").pack(side=tk.LEFT, padx=(8, 0))

        btn_close = tk.Button(
            hdr,
            text="✕",
            font=("Segoe UI", 9, "bold"),
            fg=FG_SUBTEXT,
            bg="#181825",
            activeforeground=ACCENT_RED,
            activebackground="#181825",
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            command=lambda: self._close_toast(toast),
        )
        btn_close.pack(side=tk.RIGHT)

        # Corpo
        body = tk.Frame(toast, bg=BG_PANEL, padx=10, pady=8)
        body.pack(fill=tk.BOTH, expand=True)

        prov_lbl = f"{prov_name} • {model}"
        if len(prov_lbl) > 42:
            prov_lbl = prov_lbl[:40] + "..."
        tk.Label(body, text=prov_lbl, font=("Segoe UI", 9, "bold"), fg=FG_TEXT, bg=BG_PANEL, anchor=tk.W).pack(fill=tk.X)

        tokens_frame = tk.Frame(body, bg=BG_PANEL)
        tokens_frame.pack(fill=tk.X, pady=(4, 6))

        tk.Label(tokens_frame, text=f"📊 Total: {t_tokens} tokens", font=("Segoe UI", 10, "bold"), fg=ACCENT_YELLOW, bg=BG_PANEL).pack(side=tk.LEFT)
        tk.Label(tokens_frame, text=f" (Prompt: {p_tokens} | Resposta: {c_tokens})", font=("Segoe UI", 8), fg=FG_SUBTEXT, bg=BG_PANEL).pack(side=tk.LEFT, padx=(4, 0))

        # Links/Botões de inspeção
        actions = tk.Frame(body, bg=BG_PANEL)
        actions.pack(fill=tk.X, pady=(2, 0))

        btn_prompt = tk.Button(
            actions,
            text="📄 Ver Prompt Enviado",
            command=lambda: self._open_prompt_modal(details),
            font=("Segoe UI", 9, "underline"),
            fg=ACCENT_BLUE,
            bg=BG_PANEL,
            activeforeground="#b4befe",
            activebackground=BG_PANEL,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=0,
            pady=0,
        )
        btn_prompt.pack(side=tk.LEFT, padx=(0, 14))

        btn_resp = tk.Button(
            actions,
            text="💬 Ver Resposta do Provider",
            command=lambda: self._open_response_modal(details),
            font=("Segoe UI", 9, "underline"),
            fg=ACCENT_GREEN,
            bg=BG_PANEL,
            activeforeground="#a6e3a1",
            activebackground=BG_PANEL,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=0,
            pady=0,
        )
        btn_resp.pack(side=tk.LEFT)

        toast.update_idletasks()
        w = max(340, toast.winfo_reqwidth())
        h = max(115, toast.winfo_reqheight())
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = screen_w - w - 24
        y = screen_h - h - 60
        toast.geometry(f"{w}x{h}+{x}+{y}")

        toast.after(8000, lambda: self._close_toast(toast))

    def _test_toast(self):
        mock_details = {
            "provider": "Groq",
            "model": "llama-3.3-70b-versatile",
            "latency_ms": 385.4,
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 128,
                "total_tokens": 170,
            },
            "prompt": {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "Você é um assistente útil e conciso."},
                    {"role": "user", "content": "Olá! Testando a notificação flutuante do Knowledge Ship."},
                ],
                "temperature": 0.7,
                "stream": True,
            },
            "response": "Olá! A notificação flutuante do Knowledge Ship está funcionando perfeitamente! Os tokens e os links para ver o prompt e a resposta estão 100% operacionais.",
        }
        self._show_request_toast(mock_details)

    def _open_prompt_modal(self, details: Dict[str, Any]):
        prov_name = details.get("provider", "Provedor")
        model = details.get("model", "")
        prompt_data = details.get("prompt", "")

        modal = tk.Toplevel(self.root)
        modal.title(f"Prompt Enviado - {prov_name} ({model})")
        modal.geometry("780x540")
        modal.configure(bg=BG_PANEL)
        modal.attributes("-topmost", True)

        try:
            modal.geometry("+%d+%d" % (self.root.winfo_rootx() + 80, self.root.winfo_rooty() + 80))
        except Exception:
            pass

        hdr = tk.Frame(modal, bg=BG_DARK, padx=14, pady=10)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=f"📄 Payload / Prompt Enviado para {prov_name}", font=FONT_TITLE, fg=ACCENT_BLUE, bg=BG_DARK).pack(side=tk.LEFT)

        txt_frame = tk.Frame(modal, bg=BG_PANEL, padx=14, pady=10)
        txt_frame.pack(fill=tk.BOTH, expand=True)

        txt = scrolledtext.ScrolledText(
            txt_frame,
            wrap=tk.WORD,
            bg=BG_INPUT,
            fg=FG_TEXT,
            font=FONT_CODE,
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        txt.pack(fill=tk.BOTH, expand=True)

        if isinstance(prompt_data, (dict, list)):
            formatted_text = json.dumps(prompt_data, indent=2, ensure_ascii=False)
        else:
            formatted_text = str(prompt_data)

        txt.insert(tk.END, formatted_text)
        txt.config(state=tk.DISABLED)

        btn_bar = tk.Frame(modal, bg=BG_PANEL, padx=14, pady=10)
        btn_bar.pack(fill=tk.X)

        def _copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(formatted_text)
            messagebox.showinfo("Copiado", "Prompt copiado para a área de transferência!", parent=modal)

        tk.Button(btn_bar, text="📋 Copiar", command=_copy, font=FONT_BOLD, fg="#11111b", bg=ACCENT_BLUE, relief=tk.FLAT, padx=12, pady=4, cursor="hand2").pack(side=tk.LEFT)
        tk.Button(btn_bar, text="Fechar", command=modal.destroy, font=FONT_MAIN, fg=FG_TEXT, bg=BG_INPUT, relief=tk.FLAT, padx=12, pady=4, cursor="hand2").pack(side=tk.RIGHT)

    def _open_response_modal(self, details: Dict[str, Any]):
        prov_name = details.get("provider", "Provedor")
        model = details.get("model", "")
        response_data = details.get("response", "")

        modal = tk.Toplevel(self.root)
        modal.title(f"Resposta do Provider - {prov_name} ({model})")
        modal.geometry("780x540")
        modal.configure(bg=BG_PANEL)
        modal.attributes("-topmost", True)

        try:
            modal.geometry("+%d+%d" % (self.root.winfo_rootx() + 90, self.root.winfo_rooty() + 90))
        except Exception:
            pass

        hdr = tk.Frame(modal, bg=BG_DARK, padx=14, pady=10)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=f"💬 Resposta Recebida de {prov_name}", font=FONT_TITLE, fg=ACCENT_GREEN, bg=BG_DARK).pack(side=tk.LEFT)

        txt_frame = tk.Frame(modal, bg=BG_PANEL, padx=14, pady=10)
        txt_frame.pack(fill=tk.BOTH, expand=True)

        txt = scrolledtext.ScrolledText(
            txt_frame,
            wrap=tk.WORD,
            bg=BG_INPUT,
            fg=FG_TEXT,
            font=FONT_MAIN,
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        txt.pack(fill=tk.BOTH, expand=True)

        if isinstance(response_data, (dict, list)):
            formatted_text = json.dumps(response_data, indent=2, ensure_ascii=False)
        else:
            formatted_text = str(response_data)

        txt.insert(tk.END, formatted_text)
        txt.config(state=tk.DISABLED)

        btn_bar = tk.Frame(modal, bg=BG_PANEL, padx=14, pady=10)
        btn_bar.pack(fill=tk.X)

        def _copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(formatted_text)
            messagebox.showinfo("Copiado", "Resposta copiada para a área de transferência!", parent=modal)

        tk.Button(btn_bar, text="📋 Copiar", command=_copy, font=FONT_BOLD, fg="#11111b", bg=ACCENT_GREEN, relief=tk.FLAT, padx=12, pady=4, cursor="hand2").pack(side=tk.LEFT)
        tk.Button(btn_bar, text="Fechar", command=modal.destroy, font=FONT_MAIN, fg=FG_TEXT, bg=BG_INPUT, relief=tk.FLAT, padx=12, pady=4, cursor="hand2").pack(side=tk.RIGHT)

    def _on_network_mode_changed(self):
        choice = self.var_network_mode.get()
        if choice == "lan":
            app_config.server.host = "0.0.0.0"
        else:
            app_config.server.host = "127.0.0.1"
        app_config.save()
        self._update_curl_preview()
        messagebox.showinfo(
            "Configuração Salva",
            f"Host alterado para {app_config.server.host}.\n"
            f"Reinicie o aplicativo para o servidor ligar na nova interface de rede.",
        )

    def _on_auth_changed(self):
        app_config.server.require_auth = self.var_require_auth.get()
        app_config.save()
        self._update_curl_preview()

    def _on_generate_token_click(self):
        new_token = generate_bearer_token()
        self.entry_token.delete(0, tk.END)
        self.entry_token.insert(0, new_token)
        self.var_require_auth.set(True)
        self._on_save_network_security()

    def _on_save_network_security(self):
        token = self.entry_token.get().strip()
        app_config.server.auth_token = token
        app_config.server.require_auth = self.var_require_auth.get()
        app_config.save()
        self._update_curl_preview()
        messagebox.showinfo("Sucesso", "Configurações de rede e segurança salvas com sucesso!")

    def get_effective_provider(self, provider_id: Optional[str] = None) -> Optional[ProviderConfig]:
        """Retorna o provedor real que receberá ou recebeu a requisição."""
        if provider_id:
            p = app_config.get_provider(provider_id)
            if p:
                return p

        # 1. Se o usuário selecionou um modo manual no combobox da aba Chat
        if hasattr(self, "mode_var"):
            selected_mode = self.mode_var.get()
            if selected_mode and not selected_mode.startswith("auto"):
                prov_id = selected_mode.split()[0]
                p = app_config.get_provider(prov_id)
                if p:
                    return p

        # 2. Se um provedor respondeu na última chamada do chat
        if getattr(self, "last_used_provider_id", None):
            p = app_config.get_provider(self.last_used_provider_id)
            if p:
                return p

        # 3. Primeiro candidato elegível segundo o roteador
        try:
            candidates = router.get_candidate_providers()
            if candidates:
                return candidates[0]
        except Exception:
            pass

        # 4. Primeiro provedor habilitado no config
        for p in app_config.providers:
            if p.enabled:
                return p

        # 5. Qualquer provedor existente
        return app_config.providers[0] if app_config.providers else None

    def get_provider_chat_payload(
        self, provider: Optional[ProviderConfig] = None
    ) -> Tuple[Dict[str, Any], str, Optional[ProviderConfig]]:
        """
        Retorna o payload real enviado diretamente para a API do provedor externo,
        contendo o modelo real do provedor, o prompt do usuário e a flag stream.
        """
        if provider is None:
            provider = self.get_effective_provider()

        prompt = ""
        source = "Exemplo padrão"
        if hasattr(self, "input_entry"):
            txt = self.input_entry.get().strip()
            if txt:
                prompt = txt
                source = "Prompt digitado no campo de entrada"

        if not prompt and getattr(self, "last_sent_prompt", None):
            prompt = self.last_sent_prompt
            source = "Última mensagem enviada no chat"

        if not prompt:
            prompt = "Olá, barramento de fallback!"

        model_name = provider.model if provider else "default-model"
        stream_val = self.stream_var.get() if hasattr(self, "stream_var") else True

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "stream": stream_val,
        }
        return payload, source, provider

    def generate_provider_curl_command(
        self, provider: Optional[ProviderConfig] = None, payload: Optional[Dict[str, Any]] = None
    ) -> str:
        """Gera o comando cURL real enviado diretamente para o endpoint oficial do provedor externo (sem localhost)."""
        if provider is None:
            provider = self.get_effective_provider()

        if payload is None:
            payload, _, provider = self.get_provider_chat_payload(provider)

        if not provider:
            return "# Nenhum provedor configurado no momento."

        url = get_provider_endpoint_url(provider)
        headers = [
            '-H "Content-Type: application/json"',
        ]
        if provider.api_key:
            headers.append(f'-H "Authorization: Bearer {provider.api_key}"')

        custom_headers = getattr(provider, "headers", None)
        if custom_headers and isinstance(custom_headers, dict):
            for k, v in custom_headers.items():
                if k.lower() == "authorization" and not v:
                    headers = [h for h in headers if not h.startswith('-H "Authorization:')]
                else:
                    headers.append(f'-H "{k}: {v}"')

        json_str = json.dumps(payload, ensure_ascii=False)
        headers_cmd = " ".join(headers)
        return f'curl -N -X POST "{url}" {headers_cmd} -d \'{json_str}\''

    def generate_localhost_curl_command(self) -> str:
        """Gera o comando cURL para o servidor localhost (usado na aba Rede & Segurança)."""
        host = self.local_ip if app_config.server.host == "0.0.0.0" else "127.0.0.1"
        port = app_config.server.port
        url = f"http://{host}:{port}/v1/chat/completions"

        headers = ['-H "Content-Type: application/json"']
        if app_config.server.require_auth and app_config.server.auth_token:
            headers.append(f'-H "Authorization: Bearer {app_config.server.auth_token}"')

        payload = {
            "model": "auto",
            "messages": [{"role": "user", "content": "Olá, barramento!"}],
            "stream": True,
        }
        json_str = json.dumps(payload, ensure_ascii=False)
        headers_cmd = " ".join(headers)
        return f'curl -N -X POST "{url}" {headers_cmd} -d \'{json_str}\''

    def _update_curl_preview(self):
        """Atualiza a caixa de texto de cURL da aba Rede & Segurança."""
        curl_cmd = self.generate_localhost_curl_command()
        if hasattr(self, "text_curl_preview"):
            self.text_curl_preview.delete("1.0", tk.END)
            self.text_curl_preview.insert("1.0", curl_cmd)

    def copy_curl_to_clipboard(self):
        """Copia o comando cURL real do provedor para a área de transferência."""
        provider = self.get_effective_provider()
        curl_cmd = self.generate_provider_curl_command(provider)
        self.root.clipboard_clear()
        self.root.clipboard_append(curl_cmd)
        p_name = provider.name if provider else "Provedor"
        messagebox.showinfo("Copiado!", f"Comando cURL real para '{p_name}' copiado com sucesso!")

    def show_payload_modal(self):
        """Abre uma janela modal moderna com a visualização do JSON real enviado para a API externa do provedor e o comando cURL direto."""
        modal = tk.Toplevel(self.root)
        modal.title("Inspeção de Payload Real do Provedor & cURL Externo")
        modal.geometry("820x670")
        modal.minsize(700, 520)
        modal.configure(bg=BG_DARK)
        modal.transient(self.root)
        modal.grab_set()

        try:
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 410
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 335
            modal.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        current_prov = self.get_effective_provider()

        # Cabeçalho da Janela Modal
        hdr_frame = tk.Frame(modal, bg=BG_PANEL, padx=16, pady=12)
        hdr_frame.pack(fill=tk.X)

        tk.Label(
            hdr_frame,
            text="📦 Payload Real Enviado para a API Oficial do Provedor",
            font=FONT_TITLE,
            fg=ACCENT_PURPLE,
            bg=BG_PANEL,
        ).pack(anchor=tk.W)

        # Barra de seleção de provedor dentro do modal
        sel_bar = tk.Frame(hdr_frame, bg=BG_PANEL)
        sel_bar.pack(fill=tk.X, pady=(8, 4))

        tk.Label(
            sel_bar,
            text="Provedor Alvo:",
            font=FONT_BOLD,
            fg=FG_TEXT,
            bg=BG_PANEL,
        ).pack(side=tk.LEFT, padx=(0, 8))

        prov_options = [f"{p.id} ({p.name} - {p.model})" for p in app_config.providers]
        modal_prov_var = tk.StringVar()

        # Define valor inicial
        initial_sel = prov_options[0] if prov_options else ""
        if current_prov:
            for opt in prov_options:
                if opt.startswith(f"{current_prov.id} ("):
                    initial_sel = opt
                    break
        modal_prov_var.set(initial_sel)

        combo_modal_prov = ttk.Combobox(
            sel_bar,
            textvariable=modal_prov_var,
            values=prov_options,
            state="readonly",
            width=40,
            font=FONT_MAIN,
        )
        combo_modal_prov.pack(side=tk.LEFT, fill=tk.X, expand=True)

        lbl_info = tk.Label(
            hdr_frame,
            text="",
            font=FONT_MAIN,
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
            justify=tk.LEFT,
        )
        lbl_info.pack(anchor=tk.W, pady=(4, 0))

        content_box = tk.Frame(modal, bg=BG_DARK, padx=16, pady=10)
        content_box.pack(fill=tk.BOTH, expand=True)

        # Seção 1: JSON do Payload Real
        sec_json = tk.Frame(content_box, bg=BG_DARK)
        sec_json.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        json_bar = tk.Frame(sec_json, bg=BG_DARK)
        json_bar.pack(fill=tk.X, pady=(0, 4))

        tk.Label(
            json_bar,
            text="📄 JSON do Payload Real (enviado no corpo da requisição HTTP):",
            font=FONT_BOLD,
            fg=ACCENT_BLUE,
            bg=BG_DARK,
        ).pack(side=tk.LEFT)

        def _copy_json():
            text = text_json.get("1.0", tk.END).strip()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo("Copiado", "JSON do payload copiado com sucesso!", parent=modal)

        tk.Button(
            json_bar,
            text="📋 Copiar JSON",
            command=_copy_json,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_BLUE,
            activebackground="#b4befe",
            relief=tk.FLAT,
            padx=10,
            pady=2,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        text_json = scrolledtext.ScrolledText(
            sec_json,
            wrap=tk.WORD,
            bg="#11111b",
            fg="#a6e3a1",
            insertbackground=FG_TEXT,
            font=("Consolas", 10),
            relief=tk.FLAT,
            height=10,
            padx=10,
            pady=8,
        )
        text_json.pack(fill=tk.BOTH, expand=True)

        # Seção 2: Comando cURL Real
        sec_curl = tk.Frame(content_box, bg=BG_DARK)
        sec_curl.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        curl_bar = tk.Frame(sec_curl, bg=BG_DARK)
        curl_bar.pack(fill=tk.X, pady=(0, 4))

        tk.Label(
            curl_bar,
            text="💻 Comando cURL Direto para a API Oficial (Sem passar por Localhost):",
            font=FONT_BOLD,
            fg=ACCENT_YELLOW,
            bg=BG_DARK,
        ).pack(side=tk.LEFT)

        def _copy_curl():
            text = text_curl.get("1.0", tk.END).strip()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo("Copiado", "Comando cURL copiado com sucesso!", parent=modal)

        tk.Button(
            curl_bar,
            text="📋 Copiar cURL",
            command=_copy_curl,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_YELLOW,
            activebackground="#f9e2af",
            relief=tk.FLAT,
            padx=10,
            pady=2,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        text_curl = scrolledtext.ScrolledText(
            sec_curl,
            wrap=tk.CHAR,
            bg="#11111b",
            fg="#89dceb",
            insertbackground=FG_TEXT,
            font=("Consolas", 9),
            relief=tk.FLAT,
            height=6,
            padx=10,
            pady=8,
        )
        text_curl.pack(fill=tk.BOTH, expand=True)

        def _update_view():
            selected_str = modal_prov_var.get()
            prov_id = selected_str.split()[0] if selected_str else None
            p = app_config.get_provider(prov_id) if prov_id else None
            payload, source, p = self.get_provider_chat_payload(p)
            c = self.generate_provider_curl_command(p, payload)

            url_txt = f"{p.base_url.rstrip('/')}/chat/completions" if p else "-"
            m_txt = p.model if p else "-"
            lbl_info.config(
                text=f"🌐 Endpoint: {url_txt}\n🤖 Modelo Oficial: {m_txt}   |   Origem: {source}   |   Stream: {'Sim' if payload.get('stream') else 'Não'}"
            )

            text_json.config(state=tk.NORMAL)
            text_json.delete("1.0", tk.END)
            text_json.insert(tk.END, json.dumps(payload, indent=2, ensure_ascii=False))
            text_json.config(state=tk.DISABLED)

            text_curl.config(state=tk.NORMAL)
            text_curl.delete("1.0", tk.END)
            text_curl.insert(tk.END, c)
            text_curl.config(state=tk.DISABLED)

        combo_modal_prov.bind("<<ComboboxSelected>>", lambda e: _update_view())

        # Rodapé
        footer = tk.Frame(modal, bg=BG_PANEL, padx=16, pady=10)
        footer.pack(fill=tk.X)

        tk.Button(
            footer,
            text="🔄 Atualizar com Texto Atual do Chat",
            command=_update_view,
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_INPUT,
            activebackground=BG_PANEL,
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        tk.Button(
            footer,
            text="Fechar",
            command=modal.destroy,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_RED,
            activebackground="#f38ba8",
            relief=tk.FLAT,
            padx=16,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        _update_view()

    def _render_syntax_highlighted_json(self, text_widget: scrolledtext.ScrolledText, obj: Any):
        """Renderiza um dicionário/objeto JSON formatado e com coloração sintática para facilitar a leitura."""
        text_widget.config(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)

        text_widget.tag_config("j_key", foreground="#89b4fa", font=("Consolas", 10, "bold"))
        text_widget.tag_config("j_str", foreground="#a6e3a1")
        text_widget.tag_config("j_num", foreground="#fab387")
        text_widget.tag_config("j_bool", foreground="#cba6f7", font=("Consolas", 10, "bold"))
        text_widget.tag_config("j_punct", foreground="#6c7086")
        text_widget.tag_config("j_text", foreground="#cdd6f4")

        if obj is None:
            text_widget.insert(tk.END, "# Nenhum payload disponível para exibição.", "j_punct")
            text_widget.config(state=tk.DISABLED)
            return

        try:
            raw_json = json.dumps(obj, indent=2, ensure_ascii=False)
        except Exception:
            raw_json = str(obj)

        token_re = re.compile(
            r'("(?:\\.|[^"\\])*")(\s*:)?|(\btrue\b|\bfalse\b|\bnull\b)|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([\{\}\[\],:])'
        )

        lines = raw_json.split("\n")
        for i, line in enumerate(lines):
            last_idx = 0
            for m in token_re.finditer(line):
                start, end = m.span()
                if start > last_idx:
                    text_widget.insert(tk.END, line[last_idx:start], "j_text")

                if m.group(1) and m.group(2):
                    text_widget.insert(tk.END, m.group(1), "j_key")
                    text_widget.insert(tk.END, m.group(2), "j_punct")
                elif m.group(1):
                    text_widget.insert(tk.END, m.group(1), "j_str")
                elif m.group(3):
                    text_widget.insert(tk.END, m.group(3), "j_bool")
                elif m.group(4):
                    text_widget.insert(tk.END, m.group(4), "j_num")
                elif m.group(5):
                    text_widget.insert(tk.END, m.group(5), "j_punct")
                last_idx = end

            if last_idx < len(line):
                text_widget.insert(tk.END, line[last_idx:], "j_text")

            if i < len(lines) - 1:
                text_widget.insert(tk.END, "\n")

        text_widget.config(state=tk.DISABLED)

    def show_curl_modal(self, details: dict):
        """Abre uma modal moderna com visualizador JSON formatado e comando cURL enviado ao provedor."""
        if not details or not isinstance(details, dict):
            return

        curl_cmd = details.get("curl", "")
        provider_name = details.get("provider", "Provedor")
        model_name = details.get("model", "-")
        url = details.get("url", "-")
        payload = details.get("payload")

        # Fallback para extrair o payload do comando cURL caso não esteja disponível diretamente
        if not payload and curl_cmd and " -d '" in curl_cmd:
            try:
                raw_json = curl_cmd.split(" -d '", 1)[1].rsplit("'", 1)[0]
                payload = json.loads(raw_json)
            except Exception:
                pass

        modal = tk.Toplevel(self.root)
        modal.title(f"Inspeção de Requisição - {provider_name}")
        modal.geometry("840x580")
        modal.minsize(680, 420)
        modal.configure(bg=BG_DARK)
        modal.transient(self.root)

        try:
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 420
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 290
            modal.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        # Cabeçalho
        hdr = tk.Frame(modal, bg=BG_PANEL, padx=16, pady=12)
        hdr.pack(fill=tk.X)

        tk.Label(
            hdr,
            text=f"🌐 Requisição Enviada: {provider_name}",
            font=FONT_TITLE,
            fg=ACCENT_BLUE,
            bg=BG_PANEL,
        ).pack(anchor=tk.W)

        sub_info = f"🤖 Modelo: {model_name}   |   🔗 Endpoint: {url}"
        tk.Label(
            hdr,
            text=sub_info,
            font=FONT_MAIN,
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
        ).pack(anchor=tk.W, pady=(4, 0))

        # Container Principal com Notebook (Abas)
        body = tk.Frame(modal, bg=BG_DARK, padx=14, pady=10)
        body.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(body)
        notebook.pack(fill=tk.BOTH, expand=True)

        # -------------------------------------------------------------
        # ABA 1: JSON View Formatado (Foco na Leitura)
        # -------------------------------------------------------------
        tab_json = tk.Frame(notebook, bg=BG_DARK, padx=8, pady=8)
        notebook.add(tab_json, text="  📄 JSON do Payload (Leitura Facilitada)  ")

        json_bar = tk.Frame(tab_json, bg=BG_DARK)
        json_bar.pack(fill=tk.X, pady=(0, 6))

        msg_count = len(payload.get("messages", [])) if (isinstance(payload, dict) and "messages" in payload) else 0
        stream_txt = "Sim" if (isinstance(payload, dict) and payload.get("stream")) else "Não"
        meta_label = f"Corpo JSON enviado (Mensagens: {msg_count} | Stream: {stream_txt}):"
        tk.Label(
            json_bar,
            text=meta_label,
            font=FONT_BOLD,
            fg=ACCENT_GREEN,
            bg=BG_DARK,
        ).pack(side=tk.LEFT)

        text_json = scrolledtext.ScrolledText(
            tab_json,
            wrap=tk.WORD,
            bg="#11111b",
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=("Consolas", 10),
            relief=tk.FLAT,
            padx=12,
            pady=10,
        )
        text_json.pack(fill=tk.BOTH, expand=True)
        self._render_syntax_highlighted_json(text_json, payload)

        # -------------------------------------------------------------
        # ABA 2: Comando cURL Completo
        # -------------------------------------------------------------
        tab_curl = tk.Frame(notebook, bg=BG_DARK, padx=8, pady=8)
        notebook.add(tab_curl, text="  💻 Comando cURL Completo  ")

        curl_bar = tk.Frame(tab_curl, bg=BG_DARK)
        curl_bar.pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            curl_bar,
            text="Comando pronto para reprodução direta no terminal (Bash / PowerShell):",
            font=FONT_BOLD,
            fg=ACCENT_YELLOW,
            bg=BG_DARK,
        ).pack(side=tk.LEFT)

        text_curl = scrolledtext.ScrolledText(
            tab_curl,
            wrap=tk.CHAR,
            bg="#11111b",
            fg="#89dceb",
            insertbackground=FG_TEXT,
            font=("Consolas", 10),
            relief=tk.FLAT,
            padx=12,
            pady=10,
        )
        text_curl.pack(fill=tk.BOTH, expand=True)
        text_curl.insert("1.0", curl_cmd)
        text_curl.config(state=tk.NORMAL)

        # Rodapé com Botões de Ação
        footer = tk.Frame(modal, bg=BG_PANEL, padx=16, pady=10)
        footer.pack(fill=tk.X)

        lbl_status = tk.Label(footer, text="", font=FONT_MAIN, fg=ACCENT_GREEN, bg=BG_PANEL)
        lbl_status.pack(side=tk.LEFT)

        def _copy_curl():
            self.root.clipboard_clear()
            self.root.clipboard_append(curl_cmd)
            lbl_status.config(text="✅ Comando cURL copiado com sucesso!")
            modal.after(2500, lambda: lbl_status.config(text="") if modal.winfo_exists() else None)

        def _copy_json():
            if payload:
                text_formatted = json.dumps(payload, indent=2, ensure_ascii=False)
                self.root.clipboard_clear()
                self.root.clipboard_append(text_formatted)
                lbl_status.config(text="✅ JSON do payload copiado com sucesso!")
                modal.after(2500, lambda: lbl_status.config(text="") if modal.winfo_exists() else None)

        btn_close = tk.Button(
            footer,
            text="Fechar",
            command=modal.destroy,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_RED,
            activebackground="#f38ba8",
            relief=tk.FLAT,
            padx=16,
            pady=4,
            cursor="hand2",
        )
        btn_close.pack(side=tk.RIGHT, padx=(8, 0))

        btn_curl_copy = tk.Button(
            footer,
            text="📋 Copiar cURL",
            command=_copy_curl,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_YELLOW,
            activebackground="#f9e2af",
            relief=tk.FLAT,
            padx=14,
            pady=4,
            cursor="hand2",
        )
        btn_curl_copy.pack(side=tk.RIGHT, padx=(0, 6))

        if payload:
            btn_json_copy = tk.Button(
                footer,
                text="📄 Copiar JSON",
                command=_copy_json,
                font=FONT_BOLD,
                fg="#11111b",
                bg=ACCENT_BLUE,
                activebackground="#b4befe",
                relief=tk.FLAT,
                padx=14,
                pady=4,
                cursor="hand2",
            )
            btn_json_copy.pack(side=tk.RIGHT, padx=(0, 6))

        modal.bind("<Escape>", lambda e: modal.destroy())

    # ==========================================================================
    # MODAL DE DETALHES & DIAGNÓSTICO DE ERROS DE PROVEDORES
    # ==========================================================================
    def _on_status_table_click(self, event):
        """Ao clicar em um provedor na lista de status, se deu erro ou aviso, abre a modal de diagnóstico."""
        region = self.tree_status.identify_region(event.x, event.y)
        if region not in ("cell", "tree", "item"):
            return
        item_id = self.tree_status.identify_row(event.y)
        if not item_id:
            return

        current_vals = self.tree_status.item(item_id, "values")
        st_text = current_vals[3] if len(current_vals) > 3 else ""

        # Se deu erro, está sem chave ou offline, abre a modal imediatamente ao clicar
        if any(kw in st_text for kw in ("Erro", "Sem Chave", "Inativo", "Offline", "Falha")):
            self.show_provider_details_modal(item_id)

    def _on_status_table_double_click(self, event):
        """Ao dar duplo clique em qualquer provedor da tabela, abre a modal de detalhes."""
        region = self.tree_status.identify_region(event.x, event.y)
        if region not in ("cell", "tree", "item"):
            return
        item_id = self.tree_status.identify_row(event.y)
        if item_id:
            self.show_provider_details_modal(item_id)

    def _on_status_table_motion(self, event):
        """Muda o cursor para 'hand2' (mãozinha) ao passar o mouse sobre provedores com erro na lista."""
        item_id = self.tree_status.identify_row(event.y)
        region = self.tree_status.identify_region(event.x, event.y)
        if item_id and region in ("cell", "tree", "item"):
            current_vals = self.tree_status.item(item_id, "values")
            st_text = current_vals[3] if len(current_vals) > 3 else ""
            if any(kw in st_text for kw in ("Erro", "Sem Chave", "Inativo", "Offline", "Falha")):
                self.tree_status.config(cursor="hand2")
                return
        self.tree_status.config(cursor="")

    def _on_view_selected_status_details(self):
        """Abre a modal de detalhes para o item selecionado ou o primeiro item com erro."""
        selected = self.tree_status.selection()
        target_id = selected[0] if selected else None

        if not target_id:
            for item_id in self.tree_status.get_children():
                vals = self.tree_status.item(item_id, "values")
                st = vals[3] if len(vals) > 3 else ""
                if any(kw in st for kw in ("Erro", "Sem Chave", "Offline")):
                    target_id = item_id
                    break

        if not target_id and app_config.providers:
            target_id = app_config.providers[0].id

        if target_id:
            self.tree_status.selection_set(target_id)
            self.show_provider_details_modal(target_id)
        else:
            messagebox.showinfo("Informação", "Nenhum provedor disponível para exibir detalhes.")

    def _diagnose_provider_health(
        self, r: Optional[Any], p: Optional[ProviderConfig]
    ) -> Tuple[str, str, str, str]:
        """
        Analisa o resultado da verificação ou estado do provedor e retorna:
        (badge_text, cor_destaque, titulo_diagnostico, explicacao_amigavel)
        """
        if not p:
            return "❓ Desconhecido", FG_SUBTEXT, "Provedor Não Encontrado", "Este provedor não consta no config.json."

        if not p.enabled or (r and r.status == "disabled"):
            return (
                "⚪ Inativo",
                FG_SUBTEXT,
                "Provedor Desativado",
                "Este provedor está desabilitado no config.json e não participará do roteamento ou fallback. Para reativá-lo, use a aba 'Configurações de Provedores'.",
            )

        if p.is_placeholder() or (r and r.status == "placeholder"):
            return (
                "🟡 Sem Chave de API",
                ACCENT_YELLOW,
                "Chave de API Ausente ou Inválida",
                "O provedor está configurado com chave vazia ou o valor de exemplo ('sua_chave_aqui'). Adicione sua chave real na aba 'Configurações de Provedores' para ativá-lo.",
            )

        if r:
            status_code = getattr(r, "status_code", None)
            err_msg = getattr(r, "error_message", "") or ""
            raw = getattr(r, "raw_response", "") or ""
            combined = f"{err_msg} {raw}".lower()

            if r.status == "online":
                lat = f"{r.latency_ms}ms" if r.latency_ms is not None else ""
                return (
                    "🟢 Online",
                    ACCENT_GREEN,
                    "Provedor 100% Operacional",
                    f"A API respondeu com sucesso ao teste de chat completion ({lat}). O provedor está ativo e pronto para atender requisições.",
                )

            if status_code == 401 or "401" in err_msg or "unauthorized" in combined or "invalid_api_key" in combined or "incorrect api key" in combined:
                return (
                    "🔴 Erro 401 (Não Autorizado)",
                    ACCENT_RED,
                    "Chave de API Inválida ou Expirada",
                    "A chave de API informada foi recusada pelo provedor. Verifique se copiou a chave correta sem espaços ou se ela possui créditos ativos no painel do serviço.",
                )

            if status_code == 403 or "403" in err_msg or "forbidden" in combined or "permission" in combined or "access_denied" in combined:
                return (
                    "🔴 Erro 403 (Acesso Proibido)",
                    ACCENT_RED,
                    "Acesso Negado pelo Provedor",
                    "A conta não tem permissão para acessar este modelo ou endpoint. Pode ser necessário habilitar o modelo no painel do provedor ou aceitar termos de uso.",
                )

            if status_code == 404 or "404" in err_msg or "not_found" in combined or "model_not_found" in combined:
                return (
                    "🔴 Erro 404 (Não Encontrado)",
                    ACCENT_RED,
                    "Modelo ou Endpoint Incorreto",
                    f"O modelo '{p.model}' não foi encontrado no catálogo do provedor ou a Base URL está incorreta (verifique se requer terminação '/v1').",
                )

            if status_code == 429 or "429" in err_msg or "rate limit" in combined or "quota" in combined or "insufficient_quota" in combined:
                return (
                    "🔴 Erro 429 (Limite Excedido)",
                    ACCENT_RED,
                    "Cota Esgotada ou Rate Limit",
                    "O limite de requisições por minuto (RPM) ou os créditos gratuitos da conta foram atingidos. Aguarde alguns instantes ou recarregue créditos.",
                )

            if status_code and status_code >= 500:
                return (
                    f"🔴 Erro {status_code} (Falha no Servidor)",
                    ACCENT_RED,
                    "Instabilidade nos Servidores do Provedor",
                    f"O servidor externo do provedor retornou código {status_code}. O serviço deles pode estar passando por instabilidade ou manutenção temporária.",
                )

            if "timeout" in combined or (r.status == "offline" and "timeout" in err_msg.lower()):
                return (
                    "🔴 Timeout (Tempo Esgotado)",
                    ACCENT_RED,
                    "Servidor Não Respondeu a Tempo",
                    "A requisição demorou mais de 10 segundos sem retorno. A API do provedor pode estar lenta ou bloqueada por firewall/proxy de rede.",
                )

            if "connect" in combined or "getaddrinfo" in combined or "name resolution" in combined:
                return (
                    "🔴 Falha de Conexão",
                    ACCENT_RED,
                    "Não Foi Possível Conectar ao Host",
                    "Falha ao resolver o domínio DNS ou conectar ao servidor. Verifique a URL do endpoint configurado e sua conexão com a internet.",
                )

            return (
                "🔴 Falha na API",
                ACCENT_RED,
                "Erro na Chamada de Teste",
                "O provedor retornou um erro ao responder à requisição. Veja os detalhes técnicos retornados pelo servidor na caixa abaixo.",
            )

        return (
            "⏳ Status Pendente",
            ACCENT_YELLOW,
            "Aguardando Verificação",
            "Este provedor ainda não foi testado nesta sessão. Clique no botão 'Testar Novamente' abaixo para verificar a conexão agora.",
        )

    def show_provider_details_modal(self, provider_id: str):
        """Abre uma janela modal moderna e compacta exibindo o motivo detalhado e diagnóstico do erro do provedor."""
        p = app_config.get_provider(provider_id)
        if not p:
            messagebox.showwarning("Aviso", f"Provedor '{provider_id}' não encontrado.")
            return

        if getattr(self, "active_details_modal", None):
            try:
                self.active_details_modal.destroy()
            except Exception:
                pass

        modal = tk.Toplevel(self.root)
        modal.title(f"Status & Diagnóstico - {p.name}")
        modal.geometry("570x530")
        modal.minsize(500, 440)
        modal.configure(bg=BG_DARK)
        modal.transient(self.root)
        modal.grab_set()

        self.active_details_modal = modal
        self.active_details_prov_id = provider_id

        def _on_close():
            self.active_details_modal = None
            self.active_details_prov_id = None
            self._active_modal_update_fn = None
            modal.destroy()

        modal.protocol("WM_DELETE_WINDOW", _on_close)
        modal.bind("<Escape>", lambda e: _on_close())

        try:
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 285
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 265
            modal.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        container = tk.Frame(modal, bg=BG_DARK, padx=14, pady=12)
        container.pack(fill=tk.BOTH, expand=True)

        # Cabeçalho
        hdr_frame = tk.Frame(container, bg=BG_PANEL, padx=14, pady=10)
        hdr_frame.pack(fill=tk.X, pady=(0, 10))

        lbl_hdr_badge = tk.Label(hdr_frame, text="", font=FONT_TITLE, bg=BG_PANEL)
        lbl_hdr_badge.pack(anchor=tk.W)

        lbl_hdr_sub = tk.Label(
            hdr_frame,
            text=f"Provedor: {p.name} ({p.id})  |  Modelo Ativo: {p.model}",
            font=FONT_MAIN,
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
        )
        lbl_hdr_sub.pack(anchor=tk.W, pady=(2, 0))

        # Quadro de informações rápidas (Status, Latência, Horário, Endpoint)
        grid_frame = tk.Frame(container, bg=BG_PANEL, padx=12, pady=8)
        grid_frame.pack(fill=tk.X, pady=(0, 10))

        lbl_quick_status = tk.Label(grid_frame, text="", font=FONT_BOLD, bg=BG_PANEL)
        lbl_quick_status.grid(row=0, column=0, sticky=tk.W, pady=2)

        lbl_quick_latency = tk.Label(grid_frame, text="", font=FONT_MAIN, fg=FG_TEXT, bg=BG_PANEL)
        lbl_quick_latency.grid(row=0, column=1, sticky=tk.W, padx=(20, 0), pady=2)

        lbl_quick_time = tk.Label(grid_frame, text="", font=FONT_MAIN, fg=FG_SUBTEXT, bg=BG_PANEL)
        lbl_quick_time.grid(row=0, column=2, sticky=tk.W, padx=(20, 0), pady=2)

        lbl_quick_url = tk.Label(
            grid_frame,
            text=f"Base URL: {p.base_url}",
            font=("Segoe UI", 9),
            fg=FG_SUBTEXT,
            bg=BG_PANEL,
            wraplength=510,
            justify=tk.LEFT,
        )
        lbl_quick_url.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(4, 0))

        # Banner de Diagnóstico Inteligente
        diag_frame = tk.Frame(container, bg=BG_INPUT, padx=12, pady=10)
        diag_frame.pack(fill=tk.X, pady=(0, 10))

        lbl_diag_title = tk.Label(diag_frame, text="", font=FONT_BOLD, bg=BG_INPUT)
        lbl_diag_title.pack(anchor=tk.W)

        lbl_diag_desc = tk.Label(
            diag_frame,
            text="",
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_INPUT,
            wraplength=510,
            justify=tk.LEFT,
        )
        lbl_diag_desc.pack(anchor=tk.W, pady=(4, 0))

        # Caixa de Detalhes Técnicos / Resposta Bruta
        tk.Label(
            container,
            text="🔍 Detalhes Técnicos / Resposta do Servidor:",
            font=FONT_BOLD,
            fg=ACCENT_BLUE,
            bg=BG_DARK,
        ).pack(anchor=tk.W, pady=(0, 4))

        text_details = scrolledtext.ScrolledText(
            container,
            wrap=tk.WORD,
            bg="#11111b",
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=FONT_CODE,
            relief=tk.FLAT,
            height=7,
            padx=10,
            pady=8,
        )
        text_details.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        def _update_modal_content():
            current_p = app_config.get_provider(provider_id) or p
            r = self.provider_health_details.get(provider_id) or router.get_provider_health(provider_id)

            badge_text, accent_color, diag_title, diag_desc = self._diagnose_provider_health(r, current_p)

            lbl_hdr_badge.config(text=f"{badge_text} - {current_p.name}", fg=accent_color)
            lbl_hdr_sub.config(text=f"Provedor: {current_p.name} ({current_p.id})  |  Modelo Ativo: {current_p.model}")

            lat_text = f"⏱️ Latência: {r.latency_ms}ms" if (r and r.latency_ms is not None) else "⏱️ Latência: -"
            time_text = f"🕒 Testado às: {r.checked_at}" if (r and getattr(r, 'checked_at', None)) else "🕒 Testado às: -"
            st_str = f"Status: {r.status.upper()}" if r else "Status: -"
            if r and getattr(r, "status_code", None):
                st_str += f" (HTTP {r.status_code})"

            lbl_quick_status.config(text=st_str, fg=accent_color)
            lbl_quick_latency.config(text=lat_text)
            lbl_quick_time.config(text=time_text)
            lbl_quick_url.config(text=f"Base URL: {current_p.base_url}")

            lbl_diag_title.config(text=f"💡 {diag_title}", fg=accent_color)
            lbl_diag_desc.config(text=diag_desc)

            details_content = ""
            if r:
                if getattr(r, "error_message", None):
                    details_content += f"Mensagem de Erro:\n{r.error_message}\n\n"
                if getattr(r, "raw_response", None):
                    raw_str = r.raw_response
                    try:
                        parsed = json.loads(raw_str)
                        raw_str = json.dumps(parsed, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                    details_content += f"Corpo da Resposta do Servidor:\n{raw_str}"
                elif not getattr(r, "error_message", None):
                    details_content = (
                        f"Resposta 200 OK do endpoint oficial.\n"
                        f"Provedor: {current_p.name}\n"
                        f"Modelo testado: {r.model or current_p.model}\n"
                        f"Latência aferida: {r.latency_ms}ms"
                    )
            else:
                if not current_p.enabled:
                    details_content = "Provedor desativado no momento. Nenhuma requisição recente realizada."
                elif current_p.is_placeholder():
                    details_content = "Chave de API não configurada. A API não pôde ser consultada."
                else:
                    details_content = "Nenhuma verificação recente registrada para este provedor."

            text_details.config(state=tk.NORMAL)
            text_details.delete("1.0", tk.END)
            text_details.insert(tk.END, details_content.strip())
            text_details.config(state=tk.DISABLED)

        self._active_modal_update_fn = _update_modal_content

        # Rodapé com Ações
        btn_bar = tk.Frame(container, bg=BG_DARK)
        btn_bar.pack(fill=tk.X)

        btn_retest = tk.Button(
            btn_bar,
            text="🔄 Testar Novamente",
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_BLUE,
            activebackground="#b4befe",
            relief=tk.FLAT,
            padx=10,
            pady=5,
            cursor="hand2",
        )
        btn_retest.pack(side=tk.LEFT, padx=(0, 6))

        def _on_retest():
            btn_retest.config(text="⏳ Testando...", state=tk.DISABLED)
            def _worker():
                current_p = app_config.get_provider(provider_id)
                if current_p:
                    res = asyncio.run(router.check_provider_health(current_p, timeout=12.0))
                    self.gui_queue.put(("health_single_result", res))
                def _done():
                    if modal.winfo_exists():
                        btn_retest.config(text="🔄 Testar Novamente", state=tk.NORMAL)
                        _update_modal_content()
                self.root.after(100, _done)
            threading.Thread(target=_worker, daemon=True).start()

        btn_retest.config(command=_on_retest)

        def _on_goto_config():
            _on_close()
            self.notebook.select(self.tab_providers)
            if hasattr(self, "tree_prov_list") and self.tree_prov_list.exists(provider_id):
                self.tree_prov_list.selection_set(provider_id)
                self._load_provider_into_form(provider_id)

        tk.Button(
            btn_bar,
            text="✏️ Ir para Configurações",
            command=_on_goto_config,
            font=FONT_MAIN,
            fg="#11111b",
            bg=ACCENT_YELLOW,
            activebackground="#f9e2af",
            relief=tk.FLAT,
            padx=10,
            pady=5,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 6))

        def _on_copy():
            text = text_details.get("1.0", tk.END).strip()
            if text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                messagebox.showinfo("Copiado", "Detalhes copiados para a área de transferência!", parent=modal)

        tk.Button(
            btn_bar,
            text="📋 Copiar Erro",
            command=_on_copy,
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_INPUT,
            activebackground=BG_PANEL,
            relief=tk.FLAT,
            padx=8,
            pady=5,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        tk.Button(
            btn_bar,
            text="Fechar",
            command=_on_close,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_RED,
            activebackground="#f38ba8",
            relief=tk.FLAT,
            padx=14,
            pady=5,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        _update_modal_content()

    # ==========================================================================
    # LÓGICA GERAL & CHAT
    # ==========================================================================
    def _update_combo_options(self):
        options = ["auto (Fallback Automático)"]
        for p in app_config.providers:
            options.append(f"{p.id} ({p.name} - {p.model})")
        self.mode_combo["values"] = options

        current = app_config.server.mode
        if current == "auto":
            self.mode_var.set(options[0])
        else:
            for opt in options:
                if opt.startswith(f"{current} ("):
                    self.mode_var.set(opt)
                    break

    def _on_mode_changed(self, event=None):
        selected = self.mode_var.get()
        if selected.startswith("auto"):
            target = "auto"
        else:
            target = selected.split()[0]
        app_config.set_mode(target)
        self.append_system_msg(f"Modo alterado para: {target.upper()}")

    def _on_thinking_toggled(self):
        val = self.thinking_var.get()
        app_config.server.show_thinking = val
        app_config.save()
        status_txt = "ativada" if val else "desativada"
        self.append_system_msg(f"Exibição de raciocínio/pensamento {status_txt}.")

    def _clear_chat(self):
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.delete("1.0", tk.END)
        self.chat_area.config(state=tk.DISABLED)

    def append_system_msg(self, text: str):
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.insert(tk.END, f"\n[Sistema] {text}\n", "system_tag")
        self.chat_area.see(tk.END)
        self.chat_area.config(state=tk.DISABLED)

    def _refresh_status_table(self):
        """Popula imediatamente a tabela de status com todos os provedores e modelos configurados."""
        if not hasattr(self, "tree_status"):
            return

        valid_ids = set()
        for p in app_config.providers:
            valid_ids.add(p.id)
            if not p.enabled:
                st = "⚪ Inativo"
                if p.id not in self.provider_health_details:
                    self.provider_health_details[p.id] = HealthResult(
                        provider_id=p.id,
                        name=p.name,
                        base_url=p.base_url,
                        status="disabled",
                        error_message="Desabilitado no config.json",
                        model=p.model,
                        checked_at=time.strftime("%H:%M:%S"),
                    )
            elif p.is_placeholder():
                st = "🟡 Sem Chave"
                if p.id not in self.provider_health_details:
                    self.provider_health_details[p.id] = HealthResult(
                        provider_id=p.id,
                        name=p.name,
                        base_url=p.base_url,
                        status="placeholder",
                        error_message="Chave de API não configurada",
                        model=p.model,
                        checked_at=time.strftime("%H:%M:%S"),
                    )
            else:
                st = "⏳ Verificando..."

            if self.tree_status.exists(p.id):
                current_vals = list(self.tree_status.item(p.id, "values"))
                if not p.enabled:
                    current_vals[2] = "-"
                    current_vals[3] = "⚪ Inativo"
                elif p.is_placeholder():
                    current_vals[2] = "-"
                    current_vals[3] = "🟡 Sem Chave"
                current_vals[0] = p.name
                current_vals[1] = p.model
                self.tree_status.item(p.id, values=current_vals)
            else:
                self.tree_status.insert(
                    "",
                    tk.END,
                    iid=p.id,
                    values=(p.name, p.model, "-", st),
                )

        # Remove provedores que foram excluídos
        for item in self.tree_status.get_children():
            if item not in valid_ids:
                self.tree_status.delete(item)

    def trigger_health_check(self):
        """Dispara verificação assíncrona das APIs configuradas, atualizando cada provedor assim que responder."""
        self._refresh_status_table()
        for p in app_config.providers:
            if p.enabled and not p.is_placeholder():
                if self.tree_status.exists(p.id):
                    self.tree_status.item(p.id, values=(p.name, p.model, "...", "⏳ Testando..."))

        def _worker():
            async def _check_each():
                tasks = [router.check_provider_health(p, timeout=10.0) for p in app_config.providers]
                for fut in asyncio.as_completed(tasks):
                    try:
                        res = await fut
                        self.gui_queue.put(("health_single_result", res))
                    except Exception:
                        pass

            asyncio.run(_check_each())

        threading.Thread(target=_worker, daemon=True).start()

    def on_send_message(self):
        if self.is_generating:
            return

        text = self.input_entry.get().strip()
        if not text:
            return

        self.last_sent_prompt = text
        self.input_entry.delete(0, tk.END)
        self.is_generating = True
        self.btn_send.config(text="Gerando...", state=tk.DISABLED)

        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.insert(tk.END, f"\nVocê: ", "user_tag")
        self.chat_area.insert(tk.END, f"{text}\n")
        self.chat_area.see(tk.END)
        self.chat_area.config(state=tk.DISABLED)

        use_stream = self.stream_var.get()
        show_thinking = self.thinking_var.get()
        mode = app_config.server.mode
        model_target = mode if mode else "auto"

        def _chat_worker():
            payload = {
                "messages": [{"role": "user", "content": text}],
                "model": model_target,
            }
            try:
                if use_stream:
                    async def _stream_req():
                        sse_gen, provider = await router.execute_completion(payload, stream=True)
                        self.gui_queue.put(("set_last_provider", provider.id))
                        self.gui_queue.put(("start_bot_msg", f"[{provider.name}]: "))
                        in_thinking = False
                        async for chunk in sse_gen:
                            for line in chunk.splitlines():
                                if line.startswith("data: ") and line.strip() != "data: [DONE]":
                                    data_json = line[6:].strip()
                                    try:
                                        parsed = json.loads(data_json)
                                        delta = parsed.get("choices", [{}])[0].get("delta", {})
                                        r_token = delta.get("reasoning_content")
                                        token = delta.get("content") or ""

                                        if r_token and show_thinking:
                                            if not in_thinking:
                                                in_thinking = True
                                                self.gui_queue.put(("start_thinking", None))
                                            self.gui_queue.put(("thinking_token", r_token))

                                        if token:
                                            if in_thinking:
                                                in_thinking = False
                                                self.gui_queue.put(("end_thinking", None))
                                            self.gui_queue.put(("stream_token", token))
                                    except Exception:
                                        pass
                        if in_thinking:
                            self.gui_queue.put(("end_thinking", None))
                        self.gui_queue.put(("finish_generation", None))

                    asyncio.run(_stream_req())
                else:
                    async def _block_req():
                        res, provider = await router.execute_completion(payload, stream=False)
                        self.gui_queue.put(("set_last_provider", provider.id))
                        msg = res.get("choices", [{}])[0].get("message", {})
                        content = msg.get("content", "")
                        reasoning = msg.get("reasoning_content", "")
                        self.gui_queue.put(("start_bot_msg", f"[{provider.name}]: "))
                        if reasoning and show_thinking:
                            self.gui_queue.put(("start_thinking", None))
                            self.gui_queue.put(("thinking_token", reasoning))
                            self.gui_queue.put(("end_thinking", None))
                        self.gui_queue.put(("stream_token", content))
                        self.gui_queue.put(("finish_generation", None))

                    asyncio.run(_block_req())

            except Exception as e:
                self.gui_queue.put(("error_msg", str(e)))
                self.gui_queue.put(("finish_generation", None))

        threading.Thread(target=_chat_worker, daemon=True).start()

    def _process_queue(self):
        try:
            while not self.gui_queue.empty():
                msg_type, data = self.gui_queue.get_nowait()

                if msg_type in ("health_results", "health_single_result"):
                    items = data if msg_type == "health_results" else [data]
                    for r in items:
                        self.provider_health_details[r.provider_id] = r
                        prov = app_config.get_provider(r.provider_id)
                        m_str = (prov.model if prov else "-")
                        lat_str = f"{r.latency_ms}ms" if r.latency_ms is not None else "-"
                        if r.status == "online":
                            st_str = "🟢 Online"
                        elif r.status == "disabled":
                            st_str = "⚪ Inativo"
                        elif r.status == "placeholder":
                            st_str = "🟡 Sem Chave"
                        else:
                            st_str = "🔴 Erro"
                        if not self.tree_status.exists(r.provider_id):
                            self.tree_status.insert("", tk.END, iid=r.provider_id, values=(r.name, m_str, lat_str, st_str))
                        else:
                            self.tree_status.item(r.provider_id, values=(r.name, m_str, lat_str, st_str))

                        # Se a modal estiver aberta para este provedor, atualiza em tempo real
                        if getattr(self, "active_details_prov_id", None) == r.provider_id and hasattr(self, "_active_modal_update_fn") and callable(self._active_modal_update_fn):
                            try:
                                self._active_modal_update_fn()
                            except Exception:
                                pass

                elif msg_type == "set_last_provider":
                    self.last_used_provider_id = data

                elif msg_type == "start_bot_msg":
                    self.chat_area.config(state=tk.NORMAL)
                    self.chat_area.insert(tk.END, f"\n{data}", "bot_tag")
                    self.chat_area.see(tk.END)
                    self.chat_area.config(state=tk.DISABLED)

                elif msg_type == "start_thinking":
                    self.chat_area.config(state=tk.NORMAL)
                    self.chat_area.insert(tk.END, "\n💭 Pensamento:\n", "thinking_title_tag")
                    self.chat_area.see(tk.END)
                    self.chat_area.config(state=tk.DISABLED)

                elif msg_type == "thinking_token":
                    self.chat_area.config(state=tk.NORMAL)
                    self.chat_area.insert(tk.END, data, "thinking_tag")
                    self.chat_area.see(tk.END)
                    self.chat_area.config(state=tk.DISABLED)

                elif msg_type == "end_thinking":
                    self.chat_area.config(state=tk.NORMAL)
                    self.chat_area.insert(tk.END, "\n\n💡 Resposta:\n", "thinking_title_tag")
                    self.chat_area.see(tk.END)
                    self.chat_area.config(state=tk.DISABLED)

                elif msg_type == "stream_token":
                    self.chat_area.config(state=tk.NORMAL)
                    self.chat_area.insert(tk.END, data)
                    self.chat_area.see(tk.END)
                    self.chat_area.config(state=tk.DISABLED)

                elif msg_type == "error_msg":
                    self.chat_area.config(state=tk.NORMAL)
                    self.chat_area.insert(tk.END, f"\n❌ Erro no Barramento: {data}\n", "err_tag")
                    self.chat_area.see(tk.END)
                    self.chat_area.config(state=tk.DISABLED)

                elif msg_type == "finish_generation":
                    self.is_generating = False
                    self.btn_send.config(text="Enviar ➤", state=tk.NORMAL)
                    self.chat_area.config(state=tk.NORMAL)
                    self.chat_area.insert(tk.END, "\n")
                    self.chat_area.see(tk.END)
                    self.chat_area.config(state=tk.DISABLED)

                elif msg_type == "bus_log":
                    self._append_console_event(data)
                    level = (data.get("level") or data.get("category") or "").upper()
                    if level == "REQ_RECEIVED":
                        self._on_request_received(data)
                    elif level == "COMPLETION_FINISHED":
                        self._on_completion_finished(data)
                    elif level in ("FALLBACK", "WARN"):
                        msg = data.get("message", "")
                        for p in app_config.providers:
                            if p.name.lower() in msg.lower() or p.id.lower() in msg.lower():
                                if self.tree_status.exists(p.id):
                                    current_vals = list(self.tree_status.item(p.id, "values"))
                                    current_vals[3] = "🔴 Erro"
                                    self.tree_status.item(p.id, values=current_vals)

        except Exception:
            pass

        self.root.after(50, self._process_queue)


def run_gui():
    root = tk.Tk()
    app = LLMFallbackGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
