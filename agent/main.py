import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN
from agent import run_agent

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Per-chat conversation history
conversations: dict[int, list] = {}


def _get_history(chat_id: int) -> list:
    if chat_id not in conversations:
        conversations[chat_id] = []
    return conversations[chat_id]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Olá! Sou seu assistente de negócios.* 👋\n\n"
        "Posso te ajudar com:\n"
        "• *Pipedrive*: buscar deals, contatos, organizações; atualizar negócios; criar notas e atividades\n"
        "• *Read.ai*: listar reuniões, ver resumos e transcrições\n"
        "• *SharePoint*: buscar e ler arquivos da empresa\n\n"
        "Basta me perguntar em linguagem natural! Ex:\n"
        "_\"Quais meus deals abertos?\"_\n"
        "_\"Resuma minha última reunião\"_\n"
        "_\"Busque o contrato da empresa XYZ no SharePoint\"_\n\n"
        "Use /limpar para resetar a conversa.",
        parse_mode="Markdown",
    )


async def limpar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    conversations[chat_id] = []
    await update.message.reply_text("Conversa reiniciada! Como posso ajudar?")


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Comandos disponíveis:*\n"
        "/start — Mensagem de boas-vindas\n"
        "/limpar — Reseta o histórico da conversa\n"
        "/ajuda — Mostra esta mensagem\n\n"
        "*O que posso fazer:*\n\n"
        "*Pipedrive:*\n"
        "• Buscar negócios, contatos e organizações\n"
        "• Atualizar status, valor e etapa de deals\n"
        "• Criar notas vinculadas a deals/contatos\n"
        "• Criar e listar atividades (tarefas, ligações, reuniões)\n\n"
        "*Read.ai:*\n"
        "• Listar reuniões recentes\n"
        "• Ver resumo e pontos-chave de uma reunião\n"
        "• Acessar transcrição de reuniões\n\n"
        "*SharePoint:*\n"
        "• Buscar documentos por palavra-chave\n"
        "• Listar arquivos de uma pasta\n"
        "• Ler conteúdo de arquivos de texto",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    history = _get_history(chat_id)
    try:
        reply = run_agent(history, user_text)
    except Exception as e:
        logger.error("Agent error: %s", e, exc_info=True)
        reply = f"Ocorreu um erro ao processar sua solicitação: {e}"

    # Telegram has a 4096 char limit per message
    max_len = 4096
    if len(reply) <= max_len:
        await update.message.reply_text(reply, parse_mode="Markdown")
    else:
        for i in range(0, len(reply), max_len):
            await update.message.reply_text(reply[i : i + max_len], parse_mode="Markdown")


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("limpar", limpar))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot iniciado. Aguardando mensagens...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
