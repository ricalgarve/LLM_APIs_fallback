"""
Sistema de Log e Monitoramento em Tempo Real do Barramento de LLMs.
Permite que o servidor e o roteador emitam eventos que são exibidos na tela de Console da GUI.
"""

import threading
import time
from typing import Callable, Dict, List, Optional, Any


class BusLogger:
    """Gerenciador de eventos de log em tempo real para o barramento."""

    def __init__(self):
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._lock = threading.Lock()
        self._history: List[Dict[str, Any]] = []

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Inscreve um callback (ex: GUI) para receber novos eventos de log."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def emit(self, level: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """
        Emite um novo evento de log.
        :param level: "REQ" | "SUCCESS" | "WARN" | "ERROR" | "INFO"
        :param message: Texto descritivo
        :param details: Dados adicionais (opcional)
        """
        now = time.strftime("%H:%M:%S")
        event = {
            "timestamp": now,
            "level": level.upper(),
            "message": message,
            "details": details or {},
        }

        with self._lock:
            self._history.append(event)
            # Mantém os últimos 500 eventos no histórico
            if len(self._history) > 500:
                self._history.pop(0)

            listeners_copy = list(self._listeners)

        for listener in listeners_copy:
            try:
                listener(event)
            except Exception:
                pass

    def get_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history)


# Instância global do logger do barramento
bus_logger = BusLogger()
