import contextlib
import logging
import os
import sys
from typing import Any

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)

READAI_MCP_URL = "https://api.read.ai/mcp"
READAI_API_KEY = os.environ.get("READAI_API_KEY", "")

SYSTEM_PROMPT = """Você é um assistente comercial especializado no CRM Pipedrive e reuniões Read.ai.

**Pipedrive — o que você pode fazer:**
1. Identificar oportunidades (deals) pelo nome do cliente ou descrição (busca aproximada)
2. Listar atividades em aberto de uma oportunidade
3. Resumir uma oportunidade com base nas últimas interações, notas e atividades
4. Registrar andamentos — adicionar notas ou atividades a partir de descrição em linguagem natural
5. Buscar contatos de clientes: email e telefone pelo nome do cliente ou da pessoa

**Read.ai — o que você pode fazer:**
6. Listar reuniões recentes
7. Buscar resumo, pontos-chave e decisões de uma reunião
8. Ver atividades previstas (action items) de uma reunião
9. Identificar participantes de uma reunião

Diretrizes:
- Responda sempre em português do Brasil
- Use busca por termos parciais quando o nome não for exato
- Confirme o deal correto antes de executar ações no Pipedrive
- Apresente listas com formatação clara usando marcadores
- Seja direto e objetivo — evite respostas longas desnecessárias
- Se houver mais de um resultado possível, liste as opções e peça confirmação
"""


def _build_pipedrive_params(pipedrive_key: str) -> StdioServerParameters:
    env = {**os.environ, "PIPEDRIVE_API_KEY": pipedrive_key}
    venv_bin = os.path.dirname(sys.executable)
    cmd = os.path.join(venv_bin, "pipedrive-mcp")
    return StdioServerParameters(command=cmd, args=[], env=env)


def _format_tool(tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema,
    }


class PipedriveAgent:
    def __init__(self):
        self.conversations: dict[int, list[dict]] = {}
        self.client = anthropic.AsyncAnthropic()

    def clear_history(self, chat_id: int):
        self.conversations[chat_id] = []

    async def chat(self, chat_id: int, message: str, pipedrive_key: str) -> str:
        if chat_id not in self.conversations:
            self.conversations[chat_id] = []
        self.conversations[chat_id].append({"role": "user", "content": message})
        messages = list(self.conversations[chat_id])

        async with contextlib.AsyncExitStack() as stack:
            # ── Pipedrive MCP (subprocess) ──────────────────────────────
            pd_read, pd_write = await stack.enter_async_context(
                stdio_client(_build_pipedrive_params(pipedrive_key))
            )
            pd_session = await stack.enter_async_context(ClientSession(pd_read, pd_write))
            await pd_session.initialize()
            pd_tools = await pd_session.list_tools()

            tool_to_session: dict[str, ClientSession] = {
                t.name: pd_session for t in pd_tools.tools
            }
            all_tools = [_format_tool(t) for t in pd_tools.tools]
            logger.info("Pipedrive MCP: %d ferramentas", len(pd_tools.tools))

            # ── Read.ai MCP (SSE) — opcional ────────────────────────────
            if READAI_API_KEY:
                try:
                    ra_read, ra_write = await stack.enter_async_context(
                        sse_client(
                            READAI_MCP_URL,
                            headers={"Authorization": f"Bearer {READAI_API_KEY}"},
                        )
                    )
                    ra_session = await stack.enter_async_context(
                        ClientSession(ra_read, ra_write)
                    )
                    await ra_session.initialize()
                    ra_tools = await ra_session.list_tools()
                    for t in ra_tools.tools:
                        tool_to_session[t.name] = ra_session
                        all_tools.append(_format_tool(t))
                    logger.info("Read.ai MCP: %d ferramentas", len(ra_tools.tools))
                except Exception as e:
                    logger.warning("Read.ai MCP indisponível: %s", e)

            final_text = await _run_agent_loop(
                self.client, messages, all_tools, tool_to_session
            )

        self.conversations[chat_id].append({"role": "assistant", "content": final_text})
        return final_text


async def _run_agent_loop(
    client: anthropic.AsyncAnthropic,
    messages: list[dict],
    tools: list[dict],
    tool_to_session: dict[str, ClientSession],
) -> str:
    while True:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info("Ferramenta: %s | args: %s", block.name, block.input)
                    session = tool_to_session.get(block.name)
                    if session:
                        result_text = await _call_tool(session, block.name, block.input)
                    else:
                        result_text = f"Ferramenta '{block.name}' não disponível."
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            return "\n".join(
                block.text for block in response.content if hasattr(block, "text")
            )


async def _call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> str:
    result = await session.call_tool(name, arguments)
    return "\n".join(
        block.text if hasattr(block, "text") else str(block)
        for block in result.content
    )
