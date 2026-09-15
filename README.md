# 🚀 Barramento de Fallback de LLMs (OpenAI Localhost API)

Gerenciador inteligente e barramento de fallback para múltiplos provedores de LLM (NVIDIA NIM, Groq, OpenRouter, DeepSeek, OpenAI, Ollama, LM Studio, etc.) com **Interface Gráfica Tkinter em Abas**, gerenciamento visual completo de provedores, **Autenticação por Bearer Token**, **Liberação para Rede Local (0.0.0.0)** e **API Localhost** compatível com OpenAI.

---

## 🎨 Organização da Interface Gráfica Tkinter (`gui.py`)

A interface possui uma separação clara de responsabilidades entre as abas:

### 💬 Aba 1: Chat & Monitor (Aba Principal)
- **Foco exclusivo em conversação e monitoramento de saúde**:
  - Envio e recebimento de mensagens com streaming suave na tela.
  - Seletor rápido de modo (`auto` ou manual com exibição do modelo ativo) e switch de streaming.
  - Botão rápido **`📋 Copiar cURL Localhost`**.
  - Tabela de **Status dos Provedores & Modelos**: exibe Provedor, Modelo Ativo, Latência em `ms` e conectividade em tempo real.
  - *(Sem botões de edição ou renomeação, mantendo a tela limpa).*

### 🖥️ Aba 2: Console de Requisições (Monitor em Tempo Real)
- **Acompanhamento ao vivo de tudo o que chega via `/v1/chat/completions`**:
  - Exibe timestamp, IP do cliente, método HTTP, parâmetros recebidos (`model`, `stream`, etc.) e resumo da pergunta.
  - Registra a seleção de provedor, tentativas, fallbacks caso uma API retorne erro ou rate limit, e tempo de resposta.
  - Botão **`🧹 Limpar Console`** e **`📋 Copiar Logs`**.
  - Checkbox **`Auto-scroll`** para rolar automaticamente conforme novos eventos chegam.

### ⚙️ Aba 3: Configurações de Provedores (Aba de Gerenciamento)
- **Local dedicado para cadastrar, editar, renomear e gerenciar provedores e modelos**:
  - **Lista de Provedores à Esquerda**:
    - Botão **`⚡ Ativar / Desativar`**: altera o status ativo/inativo na hora.
    - Botão **`✏️ Renomear`**: popup para alterar o nome de exibição rapidamente.
    - Botões **`➕ Novo Provedor`** e **`🗑️ Excluir`**.
  - **Formulário de Configuração à Direita**:
    - **Nome do Provedor / Nome de Exibição**: campo no topo do formulário para editar o nome.
    - **Checkbox `✅ Provedor Ativo`**: ativa ou desativa o provedor na fila de fallback.
    - **ID Interno, Endpoint (Base URL) e API Key (com botão 👁️)**.
    - **🤖 Gerenciamento de Modelos**:
      - **Combobox de Modelo Ativo**: selecione qualquer modelo da lista do provedor ou digite um novo.
      - Botão **`➕ Adicionar à Lista`**: adiciona o modelo digitado à lista de opções do provedor.
      - Botão **`🗑️ Remover`**: remove o modelo selecionado da lista do provedor.
    - Botão **`💾 Salvar Alterações no config.json`**: grava o modelo ativo e a lista `models` no arquivo.
    - Botão **`🔍 Testar Este Provedor`**: ping imediato no modelo selecionado para validar a chave e a latência.

### 🌐 Aba 4: Rede & Segurança (Bearer Token & cURL)
- **Exposição de Rede**:
  - `127.0.0.1` (apenas localhost) ou `0.0.0.0` (toda a rede local).
- **Segurança com Bearer Token**:
  - Exigência de token para autenticação e botão `🎲 Gerar Novo Token`.
- **Pré-visualização e Cópia do cURL**.

---

## ⚡ Como Iniciar

```powershell
.\.venv\Scripts\python.exe main.py
```
*(ou execute diretamente: `.\.venv\Scripts\python.exe gui.py`)*

Para modo terminal CLI:
```powershell
.\.venv\Scripts\python.exe main.py --cli
```
