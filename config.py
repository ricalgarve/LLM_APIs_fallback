"""
Gerenciador de Configuração JSON do Barramento de LLMs.
Carrega, valida e persiste os provedores, parâmetros de rede e segurança do servidor local.
"""

import json
import secrets
import socket
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict

if getattr(sys, "frozen", False):
    # Quando empacotado como executável (.exe) portátil pelo PyInstaller
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # Quando executado diretamente via script Python
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.json"


def get_resource_path(relative_path: str) -> Path:
    """Retorna o caminho de um recurso (ícones, modelos), funcionando tanto em dev quanto no pacote PyInstaller."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path


def get_local_ip() -> str:
    """Retorna o IP da máquina na rede local."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def generate_bearer_token() -> str:
    """Gera um token Bearer seguro."""
    return f"sk-local-{secrets.token_hex(16)}"


def parse_headers_input(text: str) -> Dict[str, str]:
    """Converte texto de headers (formato linha a linha 'Header: Valor', JSON ou flags cURL -H) em um dicionário."""
    text = (text or "").strip()
    if not text:
        return {}

    # Tenta como JSON se estiver entre chaves
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {str(k).strip(): str(v).strip() for k, v in data.items() if str(k).strip()}
        except Exception:
            pass

    headers: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Remove prefixo -H ou --header do cURL se copiado de documentação ou terminal
        if line.startswith(("-H ", "--header ")):
            line = line.split(maxsplit=1)[1].strip()

        # Remove aspas externas se houver (ex: "Api-Revision: 2026-05-20" ou 'Api-Revision: 2026-05-20')
        if (line.startswith('"') and line.endswith('"')) or (line.startswith("'") and line.endswith("'")):
            line = line[1:-1].strip()

        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key:
                headers[key] = val

    return headers


def format_headers_for_display(headers: Optional[Dict[str, str]]) -> str:
    """Formata o dicionário de headers para exibição no campo de texto da interface."""
    if not headers or not isinstance(headers, dict):
        return ""
    return "\n".join(f"{k}: {v}" for k, v in headers.items())


@dataclass
class ProviderConfig:
    id: str
    name: str
    base_url: str
    api_key: str
    model: str
    models: List[str] = field(default_factory=list)
    enabled: bool = True
    headers: Dict[str, str] = field(default_factory=dict)
    signup_url: str = ""

    def is_placeholder(self) -> bool:
        """Verifica se a chave de API ainda é um placeholder."""
        if not self.api_key:
            if self.is_local():
                return False
            # Se possui header de autenticação configurado com valor real (ex: x-goog-api-key), considera válido
            custom_headers = getattr(self, "headers", None) or {}
            for k, v in custom_headers.items():
                if k.lower() in ("x-goog-api-key", "api-key", "x-api-key", "authorization"):
                    if v and not any(p in v.lower() for p in ("sua_chave", "sua-chave", "your_api_key", "seu-token", "placeholder")):
                        return False
            return True

        placeholders = (
            "sua_chave_aqui",
            "gsk_sua_chave_aqui",
            "sk-or-v1-sua_chave_aqui",
            "sk-sua_chave_aqui",
            "nvapi-seu-token-aqui",
            "sua-chave-aqui",
            "sua_chave_mistral_aqui",
            "sua_chave_gemini_aqui",
            "sua_chave",
            "seu-token-aqui",
            "your_api_key",
        )
        return any(p in self.api_key for p in placeholders)

    def is_local(self) -> bool:
        """Verifica se o endpoint é local (Ollama, LM Studio, etc.)."""
        return any(
            h in self.base_url
            for h in ("localhost", "127.0.0.1", "0.0.0.0", ":11434", ":1234")
        )


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    mode: str = "auto"  # "auto" para fallback ou ID de um provedor específico
    timeout_seconds: int = 60
    default_stream: bool = True
    show_thinking: bool = True
    require_auth: bool = False
    auth_token: str = ""


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    providers: List[ProviderConfig] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "AppConfig":
        """Carrega a configuração do arquivo JSON especificado.
        Se não existir, tenta inicializar a partir de config.example.json ou cria a configuração padrão.
        """
        if not path.exists():
            # Tenta inicializar a partir de config.example.json se existir no mesmo diretório
            example_path = path.parent / "config.example.json"
            if example_path.exists():
                try:
                    loaded_example = cls._load_from_file(example_path)
                    loaded_example.save(path)
                    print(f"[INFO] '{path.name}' não encontrado. Criado novo arquivo a partir de '{example_path.name}'.")
                    return loaded_example
                except Exception as e:
                    print(f"[AVISO] Falha ao ler '{example_path.name}': {e}. Usando configuração padrão embutida.")

            default_cfg = cls._create_default()
            default_cfg.save(path)
            print(f"[INFO] '{path.name}' não encontrado. Criado novo arquivo com as configurações padrão.")
            return default_cfg

        return cls._load_from_file(path)

    @classmethod
    def _load_from_file(cls, path: Path) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        server_data = data.get("server", {})
        server_cfg = ServerConfig(
            host=server_data.get("host", "127.0.0.1"),
            port=int(server_data.get("port", 8000)),
            mode=server_data.get("mode", "auto"),
            timeout_seconds=int(server_data.get("timeout_seconds", 60)),
            default_stream=bool(server_data.get("default_stream", True)),
            show_thinking=bool(server_data.get("show_thinking", True)),
            require_auth=bool(server_data.get("require_auth", False)),
            auth_token=str(server_data.get("auth_token", "")),
        )

        providers = []
        for p in data.get("providers", []):
            raw_models = p.get("models")
            if isinstance(raw_models, list):
                models_list = [str(m).strip() for m in raw_models if str(m).strip()]
            else:
                models_list = []

            active_model = str(p.get("model", "")).strip()
            if not active_model and models_list:
                active_model = models_list[0]
            elif active_model and active_model not in models_list:
                models_list.insert(0, active_model)

            raw_headers = p.get("headers", {})
            headers_dict = {}
            if isinstance(raw_headers, dict):
                headers_dict = {str(k).strip(): str(v).strip() for k, v in raw_headers.items() if str(k).strip()}

            providers.append(
                ProviderConfig(
                    id=p["id"],
                    name=p["name"],
                    base_url=p["base_url"],
                    api_key=p.get("api_key", ""),
                    model=active_model,
                    models=models_list,
                    enabled=bool(p.get("enabled", True)),
                    headers=headers_dict,
                    signup_url=str(p.get("signup_url") or p.get("console_url") or "").strip(),
                )
            )

        return cls(server=server_cfg, providers=providers)

    def save(self, path: Path = CONFIG_PATH) -> None:
        data = {
            "server": asdict(self.server),
            "providers": [asdict(p) for p in self.providers],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        for p in self.providers:
            if p.id.lower() == provider_id.lower():
                return p
        return None

    def get_enabled_providers(self) -> List[ProviderConfig]:
        return [p for p in self.providers if p.enabled and not p.is_placeholder()]

    def set_mode(self, mode: str) -> None:
        self.server.mode = mode
        self.save()

    def upsert_provider(self, provider: ProviderConfig, old_id: Optional[str] = None) -> None:
        """Adiciona ou atualiza um provedor na lista, permitindo renomear o ID ou Nome."""
        target_id = (old_id or provider.id).lower()
        for i, p in enumerate(self.providers):
            if p.id.lower() == target_id:
                self.providers[i] = provider
                self.save()
                return
        self.providers.append(provider)
        self.save()

    def toggle_provider(self, provider_id: str) -> Optional[bool]:
        """Alterna o status ativado/desativado de um provedor."""
        p = self.get_provider(provider_id)
        if p:
            p.enabled = not p.enabled
            self.save()
            return p.enabled
        return None

    def rename_provider(self, provider_id: str, new_name: str) -> bool:
        """Altera o nome de exibição de um provedor."""
        p = self.get_provider(provider_id)
        if p and new_name.strip():
            p.name = new_name.strip()
            self.save()
            return True
        return False

    def delete_provider(self, provider_id: str) -> bool:
        """Remove um provedor da lista."""
        initial_len = len(self.providers)
        self.providers = [p for p in self.providers if p.id.lower() != provider_id.lower()]
        if len(self.providers) != initial_len:
            self.save()
            return True
        return False

    def set_provider_model(self, provider_id: str, new_model: str) -> bool:
        """Define o modelo ativo de um provedor e garante que ele esteja na lista models."""
        p = self.get_provider(provider_id)
        if p and new_model.strip():
            m = new_model.strip()
            p.model = m
            if m not in p.models:
                p.models.append(m)
            self.save()
            return True
        return False

    def add_model_to_provider(self, provider_id: str, new_model: str) -> bool:
        """Adiciona um novo modelo à lista de modelos disponíveis do provedor."""
        p = self.get_provider(provider_id)
        if p and new_model.strip():
            m = new_model.strip()
            if m not in p.models:
                p.models.append(m)
            self.save()
            return True
        return False

    def remove_model_from_provider(self, provider_id: str, model_to_remove: str) -> bool:
        """Remove um modelo da lista do provedor."""
        p = self.get_provider(provider_id)
        if p and model_to_remove in p.models:
            p.models.remove(model_to_remove)
            if p.model == model_to_remove:
                p.model = p.models[0] if p.models else ""
            self.save()
            return True
        return False

    @classmethod
    def _create_default(cls) -> "AppConfig":
        return cls(
            server=ServerConfig(),
            providers=[
                ProviderConfig(
                    id="nvidia",
                    name="NVIDIA NIM",
                    base_url="https://integrate.api.nvidia.com/v1",
                    api_key="nvapi-seu-token-aqui",
                    model="nvidia/nemotron-3.5-lightning-30b-a3b",
                    models=[
                        "nvidia/nemotron-3.5-lightning-30b-a3b",
                        "meta/llama-3.1-70b-instruct",
                        "meta/llama-3.1-8b-instruct",
                    ],
                    enabled=True,
                    signup_url="https://build.nvidia.com/",
                ),
                ProviderConfig(
                    id="mistral",
                    name="Mistral AI",
                    base_url="https://api.mistral.ai/v1",
                    api_key="sua_chave_mistral_aqui",
                    model="open-mistral-7b",
                    models=[
                        "open-mistral-7b",
                        "open-mistral-nemo",
                        "codestral-latest",
                        "mistral-small-latest",
                        "mistral-large-latest",
                    ],
                    enabled=True,
                    signup_url="https://console.mistral.ai/",
                ),
                ProviderConfig(
                    id="ollama",
                    name="Ollama (Local)",
                    base_url="http://localhost:11434/v1",
                    api_key="ollama",
                    model="qwen3.5:latest",
                    models=[
                        "qwen3.5:latest",
                        "gemma4:31b-cloud",
                    ],
                    enabled=True,
                    signup_url="https://ollama.com/",
                ),
                ProviderConfig(
                    id="gemini",
                    name="Gemini API",
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                    api_key="sua_chave_gemini_aqui",
                    model="gemini-3.6-flash",
                    models=[
                        "gemini-3.6-flash",
                        "gemini-3.8-flash",
                    ],
                    headers={
                        "Api-Revision": "2026-05-20",
                    },
                    enabled=True,
                    signup_url="https://aistudio.google.com/app/apikey",
                ),
                ProviderConfig(
                    id="grok",
                    name="Grok API",
                    base_url="https://api.groq.com/openai/v1",
                    api_key="gsk_sua_chave_aqui",
                    model="qwen/qwen3.8-27b",
                    models=[
                        "openai/gpt-oss-20b",
                        "meta-llama/llama-prompt-guard-2-22m",
                        "qwen/qwen3.8-27b",
                    ],
                    enabled=True,
                    signup_url="https://console.groq.com/keys",
                ),
            ],
        )


# Instância global
app_config = AppConfig.load()
