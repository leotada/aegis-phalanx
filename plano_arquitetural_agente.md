# Aegis Phalanx: Ambiente de Desenvolvimento Agêntico Isolado

Este documento detalha o plano arquitetural e operacional completo para construir um ambiente de desenvolvimento agêntico isolado. 

Este setup garante que o agente de Inteligência Artificial (utilizando as CLIs oficiais como Antigravity `agy` e Claude Code `claude`) opere com privilégios de "root" dentro do container. Isso permite que ele instale pacotes e gerencie dependências livremente, mantendo-se totalmente inofensivo e isolado em relação ao sistema operacional host (openSUSE). Toda a comunicação e orquestração do fluxo de trabalho ocorrerá remotamente via Telegram, utilizando um pipeline TDD multi-modelo.

---

## 1. Objetivo e Contexto

* **Objetivo:** Construir uma infraestrutura via Podman onde Agentes de IA atuem como uma equipe de Engenharia de Software autônoma. O sistema escutará demandas de um bot no Telegram, codificará aplicando rigorosamente o TDD (Test-Driven Development), conectará-se a serviços auxiliares (como banco de dados), validará testes, fará commits semânticos e abrirá Pull Requests no GitHub.
* **Contexto de Isolamento:** O ambiente utilizará o Podman no modo *rootless* nativo do Linux. Embora a IA atue como usuário `root` *dentro* do container (sem restrições de sandbox para gerenciar o próprio ambiente), o acesso ao sistema de arquivos do computador host é fisicamente bloqueado, com exceção exclusiva da pasta do projeto mapeada (`/workspace`). O ambiente possui acesso à internet e conexão isolada ao container do banco de dados na mesma rede.

---

## 2. A Instrução Base (Prompt do Agente)

Crie um arquivo chamado `.agyrules` (para Antigravity) ou `system_prompt.txt` na raiz do seu projeto. O agente lerá este arquivo como sua "Lei Primária" de comportamento.

```text
Você é um Engenheiro de Software Autônomo focado em TDD. Você tem acesso root a este container e pode usar o terminal livremente para instalar pacotes, interagir com o Git/GitHub CLI e rodar código.

Para cada demanda recebida, você DEVE seguir o fluxo:
1. GIT: Faça checkout para uma nova branch (`feature/nome-da-tarefa`).
2. TDD (Red-Green-Refactor):
   - Escreva o teste PRIMEIRO. Execute e comprove que falha.
   - Escreva o código de implementação mínimo necessário.
   - Execute a suíte de testes inteira. Corrija até passar.
   - Refatore garantindo o Clean Code.
3. INFRA: Se precisar de banco de dados, utilize a string de conexão: `postgresql://admin:admin@db:5432/appdb`.
4. REVISÃO DE PARES E PR:
   - Faça commit semântico (Conventional Commits).
   - Envie a branch para origin (`git push origin <branch>`).
   - Use o GitHub CLI (`gh pr create`) para abrir o Pull Request detalhando a implementação e a cobertura dos testes.
   - Revise seu próprio PR via `gh pr view` ou lendo o diff. Se encontrar falhas não cobertas pelos testes, corrija, faça novo commit e atualize o PR.

Nunca conclua a tarefa sem criar o PR com os testes passando.
```

---

## 3. Infraestrutura: Podman Compose e Serviços

O arquivo `compose.yml` (na raiz do projeto) provisiona a rede isolada onde a IA interage nativamente com o banco de dados. O serviço `db` usa o profile `db` e **não sobe por padrão** — quem sobe o projeto decide se precisa do banco (`make db-up` ou `podman compose --profile db up -d db`).

```yaml
version: '3.8'

networks:
  agent_network:
    driver: bridge

services:
  # Container do Banco de Dados (opt-in — profile "db")
  db:
    image: postgres:16-alpine
    container_name: agent_postgres
    profiles: ["db"]
    environment:
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: admin
      POSTGRES_DB: appdb
    networks:
      - agent_network
    # Sem portas expostas para o host, garantindo isolamento total

  # Container do Agente
  agent:
    build:
      context: .
      dockerfile: Containerfile
    container_name: agent_workspace
    environment:
      # Infraestrutura
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID} # Segurança: Bot exclusivo para o seu usuário
      - DATABASE_URL=postgresql://admin:admin@db:5432/appdb
    volumes:
      - ./:/workspace:Z
      # Mapeamento das pastas de login/credenciais locais das CLIs oficiais
      - ~/.config/claude:/root/.config/claude:Z
      - ~/.config/antigravity:/root/.config/antigravity:Z
    networks:
      - agent_network
    working_dir: /workspace
    # Inicia o orquestrador multi-modelo
    command: python3 /workspace/telegram_listener.py
```

---

## 4. O Ambiente: Containerfile

O `Containerfile` define as ferramentas base do sistema (utilizando Fedora), incluindo Node.js (necessário para a CLI do Claude) e as dependências das ferramentas oficiais de IA.

```dockerfile
FROM fedora:latest

# Instala ferramentas base, compiladores, dependências, Node.js e NPM
RUN dnf update -y && dnf install -y \
    curl git gh make gcc nodejs npm \
    python3 python3-pip python3-devel \
    postgresql-devel \
    && dnf clean all

# Instala o Claude Code CLI (CLI Oficial da Anthropic)
RUN npm install -g @anthropic-ai/claude-code

# Instala o Antigravity CLI (CLI Oficial da Google)
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash
ENV PATH="/root/.local/bin:/usr/local/bin:$PATH"

# Instala bibliotecas do bot do Telegram e frameworks de teste
RUN pip install --no-cache-dir \
    python-telegram-bot \
    pytest pytest-xdist psycopg2-binary

WORKDIR /workspace
```

---

## 5. Pipeline Orquestrador Multi-Modelo (Integração Telegram)

A estratégia central é fragmentar a tarefa em um pipeline simulando uma equipe técnica especializada. Para garantir que o design do sistema seja **extensível, modular e agnóstico** (alinhado aos princípios **SOLID**), aplicamos padrões de design como a **Fábrica de Agentes** (Agent Factory) e o **Princípio do Aberto-Fechado (OCP)**. 

Isso permite adicionar novas ferramentas agênticas (como Aider ou Mentat) no futuro simplesmente registrando uma nova classe concreta de adapter, sem modificar a lógica do orquestrador do Telegram.

### Papéis do Pipeline e Configuração de Raciocínio (Thinking)
1. **Arquiteto (High Effort):** `gemini-3.1-pro` via CLI `agy` (com thinking level / reasoning budget alto) — Foca em planejar a arquitetura e escrever os testes (Fase RED).
2. **Desenvolvedor (Fast Code):** `gemini-3.5-flash` via CLI `agy` (com thinking level médio) — Foca em codificar a solução rapidamente (Fase GREEN).
3. **Revisor (High Effort):** `gemini-3.5-flash` via CLI `agy` (com thinking level alto) — Inspeciona segurança, complexidade ciclomática e clean code (Fase REFACTOR).
4. **GitOps (Low Effort):** `gemini-3.5-flash` via CLI `agy` (com thinking level baixo) — Documenta o PR e interage com o GitHub CLI.

---

### Código Modular: `telegram_listener.py`

Crie o script modular `telegram_listener.py`:

```python
import os
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, List, Type
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = str(os.environ.get("TELEGRAM_CHAT_ID"))

# ==========================================
# SOLID: Abstrações e Contratos (DIP)
# ==========================================

class AgentCLI(ABC):
    """
    Abstração comum para todos os agentes de IA CLI (Single Responsibility Principle).
    """
    @abstractmethod
    def build_command(self, prompt: str, model: str, reasoning_budget: str) -> List[str]:
        """Gera a lista de argumentos de terminal para executar a ferramenta."""
        pass


# ==========================================
# SOLID: Implementações Concretas (OCP / LSP)
# ==========================================

class AntigravityAgentCLI(AgentCLI):
    """Adapter para a CLI oficial do Antigravity (Google)."""
    def build_command(self, prompt: str, model: str, reasoning_budget: str) -> List[str]:
        return [
            "agy",
            "--model", model,
            "--thinking", reasoning_budget,
            "/goal", prompt
        ]


class ClaudeCodeAgentCLI(AgentCLI):
    """Adapter para a CLI oficial do Claude Code (Anthropic)."""
    def build_command(self, prompt: str, model: str, reasoning_budget: str) -> List[str]:
        return [
            "claude",
            "-p", prompt,
            "-y"  # Modo não-interativo com auto-aprovação
        ]


class AiderAgentCLI(AgentCLI):
    """Adapter opcional para o Aider (caso queira utilizá-lo no futuro)."""
    def build_command(self, prompt: str, model: str, reasoning_budget: str) -> List[str]:
        return [
            "aider",
            "--model", model,
            "--message", prompt,
            "--yes",
            "--no-auto-commits"
        ]


# ==========================================
# SOLID: Fábrica e Registro Modular (OCP / SRP)
# ==========================================

class AgentRegistry:
    """
    Fábrica extensível para resolução de instâncias de agentes sem acoplamento direto.
    """
    _registry: Dict[str, Type[AgentCLI]] = {}

    @classmethod
    def register(cls, name: str, cli_class: Type[AgentCLI]) -> None:
        cls._registry[name] = cli_class

    @classmethod
    def get_agent(cls, name: str) -> AgentCLI:
        cli_class = cls._registry.get(name)
        if not cli_class:
            raise ValueError(f"Ferramenta agêntica '{name}' não está registrada.")
        return cli_class()

# Registrando os adapters no sistema
AgentRegistry.register("agy", AntigravityAgentCLI)
AgentRegistry.register("claude", ClaudeCodeAgentCLI)
AgentRegistry.register("aider", AiderAgentCLI)


# ==========================================
# Orquestrador do Pipeline (Controller)
# ==========================================

# Configuração declarativa e mutável do pipeline
PIPELINE_CONFIG = [
    {
        "step_name": "Arquiteto (Planejamento e Testes - RED)",
        "tool": "agy",
        "model": "gemini-3.1-pro",
        "reasoning_budget": "high",
        "prompt": "Crie uma nova branch git para a feature. Leia esta demanda: '{demand}'. Atue como Arquiteto de Software. Crie APENAS a suíte de testes (TDD RED Phase) para esta funcionalidade. Execute os testes via CLI e comprove que eles falham. NÃO escreva o código de produção ainda."
    },
    {
        "step_name": "Desenvolvedor (Implementação - GREEN)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "medium",
        "prompt": "Leia os testes recém-criados que estão falhando. Escreva o código de produção mínimo e estritamente necessário para fazer os testes passarem (GREEN Phase). Rode os testes paralelamente até que tudo passe perfeitamente."
    },
    {
        "step_name": "Revisor de Código (Refatoração - REFACTOR)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "high",
        "prompt": "Atue como Staff Engineer revisor. Analise as mudanças recentes. O princípio TDD foi respeitado? O código está limpo, sem code smells e seguro? Se não, refatore o código garantindo que a suíte de testes continue passando."
    },
    {
        "step_name": "GitOps (Documentação e PR)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "low",
        "prompt": "Faça o commit de todas as alterações usando o padrão Conventional Commits. Faça o push da branch atual para origin. Use a ferramenta 'gh' (GitHub CLI) para abrir um Pull Request detalhando o que foi implementado e a cobertura dos testes."
    }
]

async def handle_demand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return

    demand = update.message.text
    await update.message.reply_text(f"🚀 Iniciando Pipeline TDD Multi-Modelo para a demanda:\n\n{demand}")

    for step in PIPELINE_CONFIG:
        await update.message.reply_text(
            f"⏳ Executando: {step['step_name']}\n🔧 CLI: `{step['tool']}` | Modelo: `{step['model']}` (Thinking: {step['reasoning_budget']})"
        )
        
        prompt_content = step['prompt'].format(demand=demand)
        
        try:
            # Obtém a implementação concreta abstraída (DIP / OCP)
            agent_cli = AgentRegistry.get_agent(step['tool'])
            command = agent_cli.build_command(
                prompt=prompt_content,
                model=step['model'],
                reasoning_budget=step['reasoning_budget']
            )
            
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                await update.message.reply_text(f"⚠️ Falha na etapa {step['step_name']}:\n\n{stderr[:1000]}")
                return
                
        except Exception as e:
            await update.message.reply_text(f"❌ Erro de sistema na etapa {step['step_name']}: {str(e)}")
            return

    await update.message.reply_text("✅ Pipeline Multi-Modelo concluído com sucesso! PR aberto no repositório.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) == ALLOWED_CHAT_ID:
        await update.message.reply_text("🤖 Sistema Multi-Agente Online. Aguardando especificações...")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_demand))
    app.run_polling()
```

---

## 6. Configuração e Inicialização

1. **Faça Login Localmente no seu Host (Fora do Container)**:
   - Para o Claude: execute `npm install -g @anthropic-ai/claude-code && claude auth login`
   - Para o Antigravity: execute o comando de login do `agy` no seu terminal.
   *Desta forma, os arquivos de sessão serão criados em `~/.config/claude` e `~/.config/antigravity` no seu host.*

2. **Obtenha as chaves de infraestrutura:**
   - Crie um bot no Telegram via **@BotFather** (`TELEGRAM_BOT_TOKEN`).
   - Identifique seu Chat ID através do **@userinfobot** (`TELEGRAM_CHAT_ID`).
   - Gere um token no GitHub (`GITHUB_TOKEN`) com permissão completa para repositórios.

3. **Crie o arquivo `.env`** na raiz do projeto (apenas com tokens de infraestrutura, sem chaves de API das IAs):
```env
GITHUB_TOKEN=ghp_suachaveaqui
TELEGRAM_BOT_TOKEN=12345:AABBBCCC
TELEGRAM_CHAT_ID=123456789
```

4. **Suba a infraestrutura:**
No terminal da sua máquina:
```bash
make build    # ou: podman compose --env-file .env -f compose.yml up -d --build
```

O banco de dados **não sobe por padrão**. Se a tarefa precisar de PostgreSQL:
```bash
make db-up    # ou: podman compose --env-file .env -f compose.yml --profile db up -d db
```

---

## 7. Fluxo Real de Operação

1. O Podman inicializa o container `agent` (o banco só sobe se você tiver executado `make db-up`). O container `agent` sobe mapeando a sua pasta local de configurações (`~/.config`).
2. Você envia pelo Telegram: *"Crie uma entidade Usuario e conecte ao banco usando SQLAlchemy. Valide o formato do email e escreva testes com Pytest provando que grava no banco e falha se o e-mail for inválido."*
3. O bot intercepta a mensagem e dispara o pipeline sequencial de engenheiros.
4. O `gemini-3.1-pro` (thinking high) é invocado através do CLI `agy` oficial utilizando as credenciais da sua conta Google ativa. Os passos seguintes rodam o `gemini-3.5-flash` sob diferentes níveis de raciocínio.
5. Seu Telegram envia uma notificação instantânea com o resultado e o link do PR no GitHub.
6. Todos os arquivos são magicamente sincronizados e persistidos no seu host, prontos para a revisão manual se necessário.
