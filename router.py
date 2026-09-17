"""
Barramento de Fallback Inteligente (Router).
Gerencia a verificação de saúde (health checks) e o roteamento/fallback automático
entre múltiplos provedores de Chat Completions.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Dict, List, Optional, Tuple, Any
import httpx

from config import app_config, ProviderConfig
from bus_logger import bus_logger

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LLMRouter")
# Silencia logs de requisição do httpx e httpcore
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@dataclass
class HealthResult:
    provider_id: str
    name: str
    base_url: str
    status: str  # "online" | "offline" | "disabled" | "placeholder" | "error"
    latency_ms: Optional[float] = None
    error_message: Optional[str] = None
    status_code: Optional[int] = None
    model: Optional[str] = None
    checked_at: Optional[str] = None
    raw_response: Optional[str] = None


class LLMRouter:
    """Roteador inteligente com fallback entre provedores."""

    def __init__(self):
        self.config = app_config
        self.last_results: Dict[str, HealthResult] = {}

    def reload_config(self):
        self.config = app_config.load()

    def get_provider_health(self, provider_id: str) -> Optional[HealthResult]:
        return self.last_results.get(provider_id)

    async def check_provider_health(self, provider: ProviderConfig, timeout: float = 15.0) -> HealthResult:
        """Verifica a integridade de um provedor específico fazendo um ping leve de completion."""
        checked_time = time.strftime("%H:%M:%S")

        if not provider.enabled:
            res = HealthResult(
                provider_id=provider.id,
                name=provider.name,
                base_url=provider.base_url,
                status="disabled",
                error_message="Desabilitado no config.json",
                model=provider.model,
                checked_at=checked_time,
            )
            self.last_results[provider.id] = res
            return res

        if provider.is_placeholder():
            res = HealthResult(
                provider_id=provider.id,
                name=provider.name,
                base_url=provider.base_url,
                status="placeholder",
                error_message="Chave de API não configurada",
                model=provider.model,
                checked_at=checked_time,
            )
            self.last_results[provider.id] = res
            return res

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        test_payload = {
            "model": provider.model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }

        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        start_time = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=test_payload)
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)

                if response.status_code == 200:
                    res = HealthResult(
                        provider_id=provider.id,
                        name=provider.name,
                        base_url=provider.base_url,
                        status="online",
                        latency_ms=elapsed_ms,
                        status_code=200,
                        model=provider.model,
                        checked_at=checked_time,
                    )
                else:
                    body_text = response.text
                    res = HealthResult(
                        provider_id=provider.id,
                        name=provider.name,
                        base_url=provider.base_url,
                        status="error",
                        latency_ms=elapsed_ms,
                        status_code=response.status_code,
                        error_message=f"HTTP {response.status_code}: {body_text[:1000]}",
                        raw_response=body_text,
                        model=provider.model,
                        checked_at=checked_time,
                    )
        except httpx.TimeoutException:
            res = HealthResult(
                provider_id=provider.id,
                name=provider.name,
                base_url=provider.base_url,
                status="offline",
                error_message=f"Timeout excedido ({timeout}s)",
                raw_response=f"O servidor não respondeu dentro do limite de {timeout} segundos.",
                model=provider.model,
                checked_at=checked_time,
            )
        except Exception as e:
            res = HealthResult(
                provider_id=provider.id,
                name=provider.name,
                base_url=provider.base_url,
                status="offline",
                error_message=str(e),
                raw_response=repr(e),
                model=provider.model,
                checked_at=checked_time,
            )

        self.last_results[provider.id] = res
        return res

    async def check_all_health(self) -> List[HealthResult]:
        """Testa todos os provedores em paralelo."""
        tasks = [self.check_provider_health(p) for p in self.config.providers]
        results = await asyncio.gather(*tasks)
        return list(results)

    def get_candidate_providers(self, requested_model: Optional[str] = None) -> List[ProviderConfig]:
        """Retorna a lista de provedores elegíveis para a requisição de acordo com o modo ou modelo solicitado."""
        self.reload_config()
        mode = self.config.server.mode

        if mode != "auto":
            # Modo manual: tenta apenas o provedor escolhido
            chosen = self.config.get_provider(mode)
            if chosen and chosen.enabled and not chosen.is_placeholder():
                return [chosen]
            logger.warning(f"Provedor '{mode}' selecionado manualmente não está disponível ou habilitado.")

        # Modo automático: retorna todos os provedores habilitados com chave configurada
        candidates = list(self.config.get_enabled_providers())

        # Se um modelo específico foi solicitado, prioriza o provedor que possui esse modelo
        if requested_model and requested_model not in ("auto", "default", "fallback"):
            matching = []
            others = []
            for p in candidates:
                p_models = getattr(p, "models", []) or [p.model]
                if p.model == requested_model or requested_model in p_models or p.id.lower() == requested_model.lower():
                    matching.append(p)
                else:
                    others.append(p)
            candidates = matching + others

        return candidates

    async def execute_completion(
        self,
        payload: Dict[str, Any],
        stream: bool = False,
    ) -> Tuple[Any, ProviderConfig]:
        """
        Executa a requisição de completion no primeiro provedor funcional.
        Se falhar, faz fallback automático para o próximo da lista.
        """
        requested_model = payload.get("model")
        candidates = self.get_candidate_providers(requested_model=requested_model)
        if not candidates:
            raise RuntimeError(
                "Nenhum provedor disponível para atender a requisição. "
                "Verifique seu config.json e configure ao menos uma API Key válida."
            )

        timeout = self.config.server.timeout_seconds
        errors = []

        for provider in candidates:
            # Clona payload para adaptar o modelo se necessário
            req_payload = dict(payload)
            p_models = getattr(provider, "models", []) or [provider.model]

            # Define modelo do provedor: se o modelo solicitado estiver na lista deste provedor, usa-o;
            # caso contrário, usa o modelo ativo do provedor (provider.model).
            if requested_model and requested_model not in ("auto", "default", "fallback") and requested_model in p_models:
                target_model = requested_model
            else:
                target_model = provider.model

            req_payload["model"] = target_model
            req_payload["stream"] = stream

            headers = {
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
            }
            url = f"{provider.base_url.rstrip('/')}/chat/completions"

            bus_logger.emit("INFO", f"Tentando {provider.name} ({target_model}) | stream={stream}")

            try:
                if stream:
                    # Para streaming, iniciamos a conexão e verificamos se respondeu 200 OK
                    client = httpx.AsyncClient(timeout=timeout)
                    req = client.build_request("POST", url, headers=headers, json=req_payload)
                    response = await client.send(req, stream=True)

                    if response.status_code == 200:
                        self.last_results[provider.id] = HealthResult(
                            provider_id=provider.id,
                            name=provider.name,
                            base_url=provider.base_url,
                            status="online",
                            status_code=200,
                            model=target_model,
                            checked_at=time.strftime("%H:%M:%S"),
                        )

                        async def sse_generator() -> AsyncGenerator[str, None]:
                            try:
                                async for line in response.aiter_lines():
                                    if line:
                                        yield f"{line}\n\n"
                            finally:
                                await response.aclose()
                                await client.aclose()

                        bus_logger.emit("SUCCESS", f"Conexão de streaming estabelecida com {provider.name} ({provider.model})")
                        return sse_generator(), provider
                    else:
                        body = await response.aread()
                        await response.aclose()
                        await client.aclose()
                        raw_body = body.decode(errors='ignore')
                        err = f"Status {response.status_code} de {provider.name}: {raw_body[:200]}"
                        self.last_results[provider.id] = HealthResult(
                            provider_id=provider.id,
                            name=provider.name,
                            base_url=provider.base_url,
                            status="error",
                            status_code=response.status_code,
                            error_message=f"HTTP {response.status_code}: {raw_body[:1000]}",
                            raw_response=raw_body,
                            model=target_model,
                            checked_at=time.strftime("%H:%M:%S"),
                        )
                        bus_logger.emit("WARN", f"Falha no provedor {provider.name}: {err}. Tentando fallback...")
                        errors.append(f"{provider.name}: {err}")
                        continue
                else:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await client.post(url, headers=headers, json=req_payload)
                        if response.status_code == 200:
                            self.last_results[provider.id] = HealthResult(
                                provider_id=provider.id,
                                name=provider.name,
                                base_url=provider.base_url,
                                status="online",
                                status_code=200,
                                model=target_model,
                                checked_at=time.strftime("%H:%M:%S"),
                            )
                            bus_logger.emit("SUCCESS", f"Resposta concluída com sucesso via {provider.name}")
                            return response.json(), provider
                        else:
                            raw_body = response.text
                            err = f"Status {response.status_code} de {provider.name}: {raw_body[:200]}"
                            self.last_results[provider.id] = HealthResult(
                                provider_id=provider.id,
                                name=provider.name,
                                base_url=provider.base_url,
                                status="error",
                                status_code=response.status_code,
                                error_message=f"HTTP {response.status_code}: {raw_body[:1000]}",
                                raw_response=raw_body,
                                model=target_model,
                                checked_at=time.strftime("%H:%M:%S"),
                            )
                            bus_logger.emit("WARN", f"Falha no provedor {provider.name}: {err}. Tentando fallback...")
                            errors.append(f"{provider.name}: {err}")
                            continue

            except Exception as e:
                err = f"Exceção ao conectar em {provider.name}: {e}"
                self.last_results[provider.id] = HealthResult(
                    provider_id=provider.id,
                    name=provider.name,
                    base_url=provider.base_url,
                    status="offline",
                    error_message=str(e),
                    raw_response=repr(e),
                    model=target_model,
                    checked_at=time.strftime("%H:%M:%S"),
                )
                bus_logger.emit("WARN", f"{err}. Tentando próximo provedor...")
                errors.append(f"{provider.name}: {err}")
                continue

        bus_logger.emit("ERROR", f"Todos os provedores de fallback falharam")
        raise RuntimeError(f"Todos os provedores de fallback falharam:\n" + "\n".join(errors))


# Instância global do roteador
router = LLMRouter()
