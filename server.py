"""
Servidor Localhost OpenAI-Compatible para o Barramento de Fallback de LLMs.
Expõe endpoints padrão /v1/chat/completions e /v1/models com suporte a streaming SSE.
"""

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from config import app_config
from router import router, LLMRouter
from bus_logger import bus_logger

bearer_scheme = HTTPBearer(auto_error=False)


def verify_bearer_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)):
    """Verifica se o Bearer token é válido quando a autenticação estiver ativada."""
    if app_config.server.require_auth and app_config.server.auth_token:
        if not credentials or credentials.credentials != app_config.server.auth_token:
            raise HTTPException(
                status_code=401,
                detail="Token de autenticação (Bearer Token) ausente ou inválido.",
                headers={"WWW-Authenticate": "Bearer"},
            )

app = FastAPI(
    title="LLM Fallback Bus - Localhost OpenAI-Compatible API",
    description="Barramento inteligente de APIs de completions com fallback automático e suporte a streaming.",
    version="1.0.0",
)

# Habilita CORS irrestrito para fácil integração com frontends web ou ferramentas locais
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = Field(default="auto")
    messages: List[ChatMessage]
    stream: Optional[bool] = None
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    max_tokens: Optional[int] = 1024


class ModeSwitchRequest(BaseModel):
    mode: str  # "auto" ou ID de um provedor (ex: "nvidia", "groq")


@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "LLM Fallback Bus",
        "mode": app_config.server.mode,
        "endpoints": {
            "completions": "/v1/chat/completions",
            "models": "/v1/models",
            "status": "/status",
            "set_mode": "/mode (POST)",
        },
    }


@app.get("/status")
async def get_status():
    """Retorna o status de saúde e latência de todos os provedores."""
    health_results = await router.check_all_health()
    return {
        "mode": app_config.server.mode,
        "providers": [
            {
                "id": r.provider_id,
                "name": r.name,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "error": r.error_message,
                "base_url": r.base_url,
            }
            for r in health_results
        ],
    }


@app.post("/mode")
async def set_mode(req: ModeSwitchRequest):
    """Alterna o modo de roteamento (auto ou ID específico)."""
    target = req.mode.strip().lower()
    if target != "auto":
        provider = app_config.get_provider(target)
        if not provider:
            raise HTTPException(
                status_code=404,
                detail=f"Provedor '{target}' não encontrado na lista de configurações.",
            )
    app_config.set_mode(target)
    return {"message": f"Modo alterado para '{target}'", "mode": target}


@app.get("/v1/models", dependencies=[Depends(verify_bearer_token)])
async def list_models():
    """Retorna a lista de modelos configurados no barramento."""
    seen_ids = set()
    models_list = [
        {
            "id": "auto",
            "object": "model",
            "owned_by": "fallback-bus",
            "permission": [],
        }
    ]
    seen_ids.add("auto")

    for p in app_config.providers:
        if not p.enabled:
            continue
        # Modelo ativo primeiro
        if p.model and p.model not in seen_ids:
            models_list.append({
                "id": p.model,
                "object": "model",
                "owned_by": p.id,
                "permission": [],
            })
            seen_ids.add(p.model)
        # Outros modelos disponíveis do provedor
        for m in getattr(p, "models", []):
            if m and m not in seen_ids:
                models_list.append({
                    "id": m,
                    "object": "model",
                    "owned_by": p.id,
                    "permission": [],
                })
                seen_ids.add(m)

    return {"object": "list", "data": models_list}


@app.post("/v1/chat/completions", dependencies=[Depends(verify_bearer_token)])
async def chat_completions(req: ChatCompletionRequest, request: Request):
    """
    Endpoint padrão compatível com OpenAI.
    Recebe as mensagens, seleciona a melhor API disponível via fallback,
    e responde com streaming SSE ou JSON completo.
    """
    # Define se o streaming deve ser usado
    should_stream = app_config.server.default_stream if req.stream is None else req.stream

    client_ip = request.client.host if request.client else "local"
    preview = ""
    if req.messages:
        preview = req.messages[-1].content[:60].replace("\n", " ")
        if len(req.messages[-1].content) > 60:
            preview += "..."

    bus_logger.emit(
        "REQ",
        f"POST /v1/chat/completions | De: {client_ip} | Modelo: {req.model} | Stream: {should_stream} | Msg: \"{preview}\"",
    )

    payload = {
        "model": req.model,
        "messages": [msg.model_dump() for msg in req.messages],
        "temperature": req.temperature,
        "top_p": req.top_p,
        "max_tokens": req.max_tokens,
    }

    try:
        result, provider = await router.execute_completion(payload, stream=should_stream)

        if should_stream:
            # Result é um gerador assíncrono de strings SSE
            return StreamingResponse(
                result,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-LLM-Provider": provider.id,
                    "X-LLM-Model": provider.model,
                },
            )
        else:
            # Result é um dicionário JSON já decodificado
            headers = {
                "X-LLM-Provider": provider.id,
                "X-LLM-Model": provider.model,
            }
            return JSONResponse(content=result, headers=headers)

    except RuntimeError as re:
        raise HTTPException(status_code=502, detail=str(re))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no barramento: {e}")


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Executa o servidor local Uvicorn."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run_server(app_config.server.host, app_config.server.port)
