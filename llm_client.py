"""
Cliente universal para consumo de qualquer API compatível com o padrão OpenAI Chat Completions.
Funciona com: OpenAI, NVIDIA NIM, Groq, OpenRouter, DeepSeek, Together AI, Mistral, Ollama, LM Studio, etc.
Suporta chamadas de completions com streaming ativado ou desativado.
"""

import sys
from typing import Generator, List, Dict, Optional, Union
from openai import OpenAI
from config import config, Settings


class LLMClient:
    """Cliente universal para APIs de LLM compatíveis com completions."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        settings: Optional[Settings] = None,
    ):
        self.settings = settings or config
        self._custom_base_url = base_url
        self._custom_api_key = api_key
        self._custom_model = default_model
        self._client: Optional[OpenAI] = None

    @property
    def base_url(self) -> str:
        return self._custom_base_url or self.settings.base_url

    @property
    def api_key(self) -> str:
        return self._custom_api_key or self.settings.api_key

    @property
    def default_model(self) -> str:
        return self._custom_model or self.settings.model

    @property
    def client(self) -> OpenAI:
        """Inicializa e retorna o cliente configurado com o endpoint e a API key especificados."""
        if self._client is None:
            self.settings.validate()
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key or "not-needed",
            )
        return self._client

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        stream: Optional[bool] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: int = 1024,
    ) -> Union[str, Generator[str, None, None]]:
        """
        Executa uma requisição de Chat Completion.
        
        :param messages: Lista de mensagens [{"role": "user"|"system"|"assistant", "content": "..."}]
        :param stream: Se True, retorna um Generator com os pedaços (tokens). Se False, retorna a string completa.
        :param model: Nome do modelo no provedor (se omitido, usa o configurado no .env).
        :param temperature: Temperatura de amostragem.
        :param top_p: Amostragem de probabilidade cumulativa (nucleus sampling).
        :param max_tokens: Limite de tokens na resposta.
        :return: Resposta completa como string (se stream=False) ou Generator de strings (se stream=True).
        """
        target_model = model or self.default_model
        should_stream = self.settings.default_stream if stream is None else stream

        response = self.client.chat.completions.create(
            model=target_model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=should_stream,
        )

        if should_stream:
            def _stream_generator() -> Generator[str, None, None]:
                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        content = getattr(delta, "content", None)
                        if content:
                            yield content

            return _stream_generator()
        else:
            return response.choices[0].message.content or ""

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        stream: Optional[bool] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> Union[str, Generator[str, None, None]]:
        """
        Gera uma resposta para um prompt simples (com ou sem system prompt).
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return self.chat_completion(
            messages=messages,
            stream=stream,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def print_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        stream: Optional[bool] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """
        Executa a geração e imprime no console.
        Se stream=True, imprime cada token imediatamente com flush no stdout para visualização em tempo real.
        Retorna o texto final gerado.
        """
        should_stream = self.settings.default_stream if stream is None else stream
        result = self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            stream=should_stream,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if should_stream:
            full_text = []
            for chunk in result:
                sys.stdout.write(chunk)
                sys.stdout.flush()
                full_text.append(chunk)
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(full_text)
        else:
            print(result)
            return result
