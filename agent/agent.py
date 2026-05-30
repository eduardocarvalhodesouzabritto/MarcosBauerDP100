import json
import anthropic
from config import ANTHROPIC_API_KEY
import tools.pipedrive as pipedrive
import tools.readai as readai
import tools.sharepoint as sharepoint

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Você é um assistente de negócios inteligente com acesso ao Pipedrive (CRM), Read.ai (reuniões) e SharePoint (arquivos da empresa).

Responda sempre em português, de forma clara e concisa. Use formatação Telegram (negrito com *texto*, itálico com _texto_) para destacar informações importantes como nomes, valores e datas.

Ao apresentar listas de resultados, seja organizado e objetivo. Pergunte ao usuário se precisa de mais detalhes sobre algum item específico."""

TOOLS = [
    {
        "name": "search_deals",
        "description": "Busca negócios/deals no Pipedrive por termo de pesquisa. Pode filtrar por status (open, won, lost).",
        "input_schema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Termo de busca (nome do deal, empresa, etc.)"},
                "status": {"type": "string", "enum": ["open", "won", "lost"], "description": "Filtrar por status"},
                "limit": {"type": "integer", "description": "Número máximo de resultados (padrão 10)", "default": 10},
            },
            "required": ["term"],
        },
    },
    {
        "name": "get_deal",
        "description": "Obtém detalhes completos de um deal específico pelo ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "integer", "description": "ID do deal no Pipedrive"},
            },
            "required": ["deal_id"],
        },
    },
    {
        "name": "update_deal",
        "description": "Atualiza campos de um deal no Pipedrive (status, valor, responsável, etapa, data de fechamento).",
        "input_schema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "integer", "description": "ID do deal"},
                "fields": {
                    "type": "object",
                    "description": "Campos a atualizar. Exemplos: {\"status\": \"won\"}, {\"value\": 5000}, {\"stage_id\": 3}, {\"expected_close_date\": \"2025-06-30\"}",
                },
            },
            "required": ["deal_id", "fields"],
        },
    },
    {
        "name": "search_persons",
        "description": "Busca contatos/pessoas no Pipedrive por nome ou email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Nome ou email do contato"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["term"],
        },
    },
    {
        "name": "search_organizations",
        "description": "Busca organizações/empresas no Pipedrive por nome.",
        "input_schema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Nome da organização"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["term"],
        },
    },
    {
        "name": "create_note",
        "description": "Cria uma nota no Pipedrive vinculada a um deal, contato ou organização.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Conteúdo da nota"},
                "deal_id": {"type": "integer", "description": "ID do deal (opcional)"},
                "person_id": {"type": "integer", "description": "ID do contato (opcional)"},
                "org_id": {"type": "integer", "description": "ID da organização (opcional)"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "create_activity",
        "description": "Cria uma atividade/tarefa no Pipedrive (ligação, reunião, email, tarefa).",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Assunto da atividade"},
                "type": {"type": "string", "description": "Tipo: call, meeting, email, task, deadline, lunch"},
                "due_date": {"type": "string", "description": "Data de vencimento (YYYY-MM-DD)"},
                "due_time": {"type": "string", "description": "Hora de vencimento (HH:MM)"},
                "deal_id": {"type": "integer", "description": "ID do deal vinculado (opcional)"},
                "person_id": {"type": "integer", "description": "ID do contato vinculado (opcional)"},
                "note": {"type": "string", "description": "Observações da atividade"},
            },
            "required": ["subject", "type"],
        },
    },
    {
        "name": "list_activities",
        "description": "Lista atividades pendentes ou concluídas do Pipedrive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "done": {"type": "integer", "enum": [0, 1], "description": "0 = pendentes, 1 = concluídas", "default": 0},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "list_meetings",
        "description": "Lista reuniões recentes do Read.ai. Pode buscar por palavra-chave.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
                "query": {"type": "string", "description": "Filtrar reuniões por palavra-chave (opcional)"},
            },
        },
    },
    {
        "name": "get_meeting_summary",
        "description": "Obtém o resumo completo de uma reunião do Read.ai, incluindo pontos-chave e itens de ação.",
        "input_schema": {
            "type": "object",
            "properties": {
                "meeting_id": {"type": "string", "description": "ID da reunião no Read.ai"},
            },
            "required": ["meeting_id"],
        },
    },
    {
        "name": "get_meeting_transcript",
        "description": "Obtém a transcrição de uma reunião do Read.ai.",
        "input_schema": {
            "type": "object",
            "properties": {
                "meeting_id": {"type": "string", "description": "ID da reunião no Read.ai"},
            },
            "required": ["meeting_id"],
        },
    },
    {
        "name": "search_sharepoint",
        "description": "Busca arquivos e documentos no SharePoint da empresa por palavra-chave.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo de busca"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_files",
        "description": "Lista arquivos e pastas em um diretório do SharePoint.",
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_path": {"type": "string", "description": "Caminho da pasta (ex: 'Documentos/Contratos'). Deixe vazio para a raiz."},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "read_file",
        "description": "Lê o conteúdo de um arquivo de texto do SharePoint pelo ID do item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID do arquivo no SharePoint (obtido via search_sharepoint ou list_files)"},
            },
            "required": ["item_id"],
        },
    },
    {
        "name": "get_file_info",
        "description": "Obtém metadados de um arquivo no SharePoint (criador, data de modificação, tamanho, URL).",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID do arquivo no SharePoint"},
            },
            "required": ["item_id"],
        },
    },
]

TOOL_HANDLERS = {
    "search_deals": lambda args: pipedrive.search_deals(**args),
    "get_deal": lambda args: pipedrive.get_deal(**args),
    "update_deal": lambda args: pipedrive.update_deal(**args),
    "search_persons": lambda args: pipedrive.search_persons(**args),
    "search_organizations": lambda args: pipedrive.search_organizations(**args),
    "create_note": lambda args: pipedrive.create_note(**args),
    "create_activity": lambda args: pipedrive.create_activity(**args),
    "list_activities": lambda args: pipedrive.list_activities(**args),
    "list_meetings": lambda args: readai.list_meetings(**args),
    "get_meeting_summary": lambda args: readai.get_meeting_summary(**args),
    "get_meeting_transcript": lambda args: readai.get_meeting_transcript(**args),
    "search_sharepoint": lambda args: sharepoint.search_sharepoint(**args),
    "list_files": lambda args: sharepoint.list_files(**args),
    "read_file": lambda args: sharepoint.read_file(**args),
    "get_file_info": lambda args: sharepoint.get_file_info(**args),
}


def run_agent(chat_history: list, user_message: str) -> str:
    chat_history.append({"role": "user", "content": user_message})

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=chat_history,
        )

        # Collect all content blocks for assistant turn
        assistant_content = response.content
        chat_history.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            return next(
                (block.text for block in assistant_content if hasattr(block, "text")),
                "Sem resposta.",
            )

        if response.stop_reason != "tool_use":
            return "Erro: resposta inesperada do modelo."

        # Execute all tool calls
        tool_results = []
        for block in assistant_content:
            if block.type != "tool_use":
                continue
            handler = TOOL_HANDLERS.get(block.name)
            if not handler:
                result = {"error": f"Ferramenta desconhecida: {block.name}"}
            else:
                try:
                    result = handler(block.input)
                except Exception as e:
                    result = {"error": str(e)}

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

        chat_history.append({"role": "user", "content": tool_results})
