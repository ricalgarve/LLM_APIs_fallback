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
import secrets
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
from typing import Optional, List

from config import app_config, ProviderConfig, get_local_ip, generate_bearer_token
from router import router
from server import run_server
from bus_logger import bus_logger

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
        self.root.title("Barramento de Fallback de LLMs - OpenAI Localhost API")
        self.root.geometry("1180x740")
        self.root.minsize(980, 620)
        self.root.configure(bg=BG_DARK)

        self.gui_queue = queue.Queue()
        self.is_generating = False
        self.local_ip = get_local_ip()
        self.current_editing_id: Optional[str] = None

        # Inicia servidor local em thread separada se a porta estiver livre
        self.start_background_server()

        # Estilos e Layout
        self._setup_styles()
        self._build_header()
        self._build_notebook_tabs()

        # Inscreve listener para receber logs do barramento em tempo real
        bus_logger.subscribe(lambda event: self.gui_queue.put(("bus_log", event)))

        # Agenda processador da fila e health check inicial
        self.root.after(50, self._process_queue)
        self.root.after(400, self.trigger_health_check)

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

    def _build_header(self):
        header_frame = tk.Frame(self.root, bg=BG_PANEL, height=55, padx=16, pady=8)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        title_lbl = tk.Label(
            header_frame,
            text="🚀 Barramento de Fallback de LLMs",
            font=FONT_TITLE,
            fg=ACCENT_BLUE,
            bg=BG_PANEL,
        )
        title_lbl.pack(side=tk.LEFT)

        api_url = f"http://{app_config.server.host}:{app_config.server.port}/v1"
        self.server_status_lbl = tk.Label(
            header_frame,
            text=f"🟢 API Ativa: {api_url}",
            font=FONT_BOLD,
            fg=ACCENT_GREEN,
            bg=BG_PANEL,
        )
        self.server_status_lbl.pack(side=tk.RIGHT)

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

        self._build_tab_chat(self.tab_chat)
        self._build_tab_console(self.tab_console)
        self._build_tab_providers(self.tab_providers)
        self._build_tab_network(self.tab_network)

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

        # Botão Copiar cURL Rápido
        btn_copy_curl = tk.Button(
            left_panel,
            text="📋 Copiar cURL Localhost",
            command=self.copy_curl_to_clipboard,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_PURPLE,
            activebackground="#b4befe",
            relief=tk.FLAT,
            pady=5,
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
        self.console_text.insert(tk.END, f"{message}\n", tag)

        if details and isinstance(details, dict):
            for k, v in details.items():
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
        right_box = tk.Frame(container, bg=BG_PANEL, padx=16, pady=16)
        right_box.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        tk.Label(right_box, text="📝 Configurações do Provedor Selecionado", font=FONT_SUBTITLE, fg=ACCENT_BLUE, bg=BG_PANEL).pack(anchor=tk.W, pady=(0, 4))
        tk.Label(right_box, text="Edite o nome, ative/desative ou altere chaves e modelos deste provedor:", font=FONT_MAIN, fg=FG_SUBTEXT, bg=BG_PANEL).pack(anchor=tk.W, pady=(0, 10))

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
        ).grid(row=2, column=0, sticky=tk.W, pady=(4, 10))

        # 3. ID do Provedor
        self.entry_prov_id = self._create_form_field(form_frame, "ID Interno (ex: nvidia, groq):", 2)

        # 4. Base URL
        self.entry_prov_url = self._create_form_field(form_frame, "Base URL do Endpoint (OpenAI-compatible):", 3)
        
        # 5. API Key com botão de exibir/ocultar
        tk.Label(form_frame, text="API Key / Token:", font=FONT_MAIN, fg=FG_TEXT, bg=BG_PANEL).grid(row=8, column=0, sticky=tk.W, pady=(6, 2))
        key_frame = tk.Frame(form_frame, bg=BG_PANEL)
        key_frame.grid(row=9, column=0, sticky="ew", pady=(0, 6))
        form_frame.columnconfigure(0, weight=1)

        self.entry_prov_key = tk.Entry(key_frame, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, font=FONT_MAIN, relief=tk.FLAT, show="•")
        self.entry_prov_key.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)

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

        # 6. Modelos do Provedor (Seletor Combobox + Adicionar / Remover)
        tk.Label(
            form_frame,
            text="🤖 Modelo Ativo (Selecione da lista ou digite para adicionar):",
            font=FONT_MAIN,
            fg=FG_TEXT,
            bg=BG_PANEL,
        ).grid(row=10, column=0, sticky=tk.W, pady=(6, 2))

        model_row = tk.Frame(form_frame, bg=BG_PANEL)
        model_row.grid(row=11, column=0, sticky="ew", pady=(0, 6))

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

        # Botões de Ação do formulário
        action_bar = tk.Frame(form_frame, bg=BG_PANEL)
        action_bar.grid(row=12, column=0, sticky="ew", pady=(14, 0))

        tk.Button(
            action_bar,
            text="💾 Salvar Alterações no config.json",
            command=self._save_current_provider,
            font=FONT_BOLD,
            fg="#11111b",
            bg=ACCENT_GREEN,
            activebackground="#a6e3a1",
            relief=tk.FLAT,
            padx=14,
            pady=7,
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
            padx=12,
            pady=7,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(10, 0))

        self._refresh_providers_list()

    def _create_form_field(self, parent, label_text: str, row: int) -> tk.Entry:
        tk.Label(parent, text=label_text, font=FONT_MAIN, fg=FG_TEXT, bg=BG_PANEL).grid(row=row*2, column=0, sticky=tk.W, pady=(6, 2))
        entry = tk.Entry(parent, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, font=FONT_MAIN, relief=tk.FLAT)
        entry.grid(row=row*2+1, column=0, sticky="ew", pady=(0, 6), ipady=5)
        return entry

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
        self.entry_prov_key.delete(0, tk.END)
        self.entry_prov_key.insert(0, p.api_key)
        models = getattr(p, "models", []) or ([p.model] if p.model else [])
        self.combo_prov_model["values"] = models
        self.combo_prov_model.set(p.model)
        self.var_prov_enabled.set(p.enabled)

    def _on_new_provider_click(self):
        self.current_editing_id = None
        self.entry_prov_id.delete(0, tk.END)
        self.entry_prov_id.insert(0, f"novo_{len(app_config.providers)+1}")
        self.entry_prov_name.delete(0, tk.END)
        self.entry_prov_name.insert(0, "Novo Provedor")
        self.entry_prov_url.delete(0, tk.END)
        self.entry_prov_url.insert(0, "https://api.exemplo.com/v1")
        self.entry_prov_key.delete(0, tk.END)
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
        key = self.entry_prov_key.get().strip()
        selected_model = self.combo_prov_model.get().strip()
        enabled = self.var_prov_enabled.get()

        if not pid or not name or not url or not selected_model:
            messagebox.showerror("Erro", "ID, Nome, Base URL e Modelo são campos obrigatórios.")
            return

        models = list(self.combo_prov_model["values"])
        if selected_model not in models:
            models.append(selected_model)

        new_p = ProviderConfig(
            id=pid,
            name=name,
            base_url=url,
            api_key=key,
            model=selected_model,
            models=models,
            enabled=enabled,
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

        def _test_worker():
            test_p = ProviderConfig(
                id=p.id,
                name=p.name,
                base_url=p.base_url,
                api_key=p.api_key,
                model=current_model,
                models=getattr(p, "models", []),
                enabled=p.enabled,
            )
            res = asyncio.run(router.check_provider_health(test_p))
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

    def generate_curl_command(self) -> str:
        """Gera o comando cURL formatado de acordo com a configuração atual."""
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
        curl_cmd = self.generate_curl_command()
        self.text_curl_preview.delete("1.0", tk.END)
        self.text_curl_preview.insert("1.0", curl_cmd)

    def copy_curl_to_clipboard(self):
        curl_cmd = self.generate_curl_command()
        self.root.clipboard_clear()
        self.root.clipboard_append(curl_cmd)
        messagebox.showinfo("Copiado!", "Comando cURL copiado com sucesso para a área de transferência!")

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
            elif p.is_placeholder():
                st = "🟡 Sem Chave"
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

        def _chat_worker():
            payload = {
                "messages": [{"role": "user", "content": text}],
                "model": "auto",
            }
            try:
                if use_stream:
                    async def _stream_req():
                        sse_gen, provider = await router.execute_completion(payload, stream=True)
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

        except Exception:
            pass

        self.root.after(50, self._process_queue)


def run_gui():
    root = tk.Tk()
    app = LLMFallbackGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
