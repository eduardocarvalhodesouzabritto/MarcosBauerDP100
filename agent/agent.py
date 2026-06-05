import logging
import os
import shutil
import sys
from typing import Any

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é um assistente comercial especializado no CRM Pipedrive.

Você auxilia vendedores e gestores com as seguintes capacidades:

1. **Identificar oportunidades (deals)**: Busca pelo nome do cliente ou descrição da oportunidade.
   O nome informado pode ser parcial ou aproximado — use busca por termos e confirme com o usuário se houver ambiguidade.

2. **Atividades em aberto**: Lista as atividades pendentes de uma oportunidade específica.

3. **Resumo da oportunidade**: Apresenta um breve resumo do deal considerando as últimas notas,
   atividades e interações registradas.

4. **Registrar andamento**: Adiciona uma nota ou atividade em uma oportunidade a partir de
   uma descrição em linguagem natural.

5. **Contatos de clientes**: Busca email e telefone de contatos pelo nome do cliente
   ou pelo nome da pessoa de contato.

Diretrizes:
- Responda sempre em português do Brasil
- Use busca por termos parciais quando o nome não for exato
- Antes de executar ações (como registrar um andamento), confirme que identificou o deal correto
- Apresente listas com formatação clara usando marcadores
- Seja direto e objetivo — evite respostas longas desnecessárias
- Se houver mais de um resultado possível, liste as opções e peça confirmação
"""


def _build_server_params() -> StdioServerParameters:
    # Prefer the installed entry-point script; fall back to `python -m`
    cmd = shutil.which("pipedrive-mcp")
    if cmd:
        return StdioServerParameters(command=cmd, args=[], env={**os.environ})
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "pipedrive_mcp"],
        env={**os.environ},
    )


class PipedriveAgent:
    def __init__(self):
        self.conversations: dict[int, list[dict]] = {}
        self.client = anthropic.AsyncAnthropic()

    def clear_history(self, chat_id: int):
        self.conversations[chat_id] = []

    async def chat(self, chat_id: int, message: str) -> str:
        if chat_id not in self.conversations:
            self.conversations[chat_id] = []

        self.conversations[chat_id].append({"role": "user", "content": message})
        messages = list(self.conversations[chat_id])

        async with stdio_client(_build_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.list_tools()
                tools = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.inputSchema,
                    }
                    for t in result.tools
                ]
                logger.info("MCP conectado — %d ferramentas", len(tools))

                final_text = await _run_agent_loop(
                    self.client, messages, tools, session
                )

        self.conversations[chat_id].append(
            {"role": "assistant", "content": final_text}
        )
        return final_text


async def _run_agent_loop(
    client: anthropic.AsyncAnthropic,
    messages: list[dict],
    tools: list[dict],
    session: ClientSession,
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
                    result_text = await _call_tool(session, block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

            messages.append({"role": "user", "content": tool_results})

        else:
            return "\n".join(
                block.text
                for block in response.content
                if hasattr(block, "text")
            )


async def _call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> str:
    result = await session.call_tool(name, arguments)
    return "\n".join(
        block.text if hasattr(block, "text") else str(block)
        for block in result.content
    )
