import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent import PipedriveAgent

load_dotenv()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

agent = PipedriveAgent()

BOAS_VINDAS = (
    "*Assistente Pipedrive*\n\n"
    "Posso te ajudar com:\n"
    "• Buscar oportunidades por cliente\n"
    "• Listar atividades em aberto\n"
    "• Resumir o status de uma oportunidade\n"
    "• Registrar andamentos\n"
    "• Buscar contatos (e-mail / telefone)\n\n"
    "Use /novo para reiniciar a conversa."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(BOAS_VINDAS, parse_mode="Markdown")


async def cmd_novo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent.clear_history(update.effective_chat.id)
    await update.message.reply_text("Conversa reiniciada! Como posso ajudar?")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_message = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        response = await agent.chat(chat_id, user_message)

        # Telegram tem limite de 4096 caracteres por mensagem
        for chunk in _split_message(response):
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(chunk)

    except Exception:
        logger.exception("Erro ao processar mensagem do chat_id=%s", chat_id)
        await update.message.reply_text(
            "Ocorreu um erro ao processar sua solicitação. Tente novamente."
        )


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


async def post_init(application: Application):
    await agent.start()
    logger.info("Agente Pipedrive pronto.")


async def post_shutdown(application: Application):
    await agent.stop()
    logger.info("Agente encerrado.")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado no .env")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("novo", cmd_novo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot iniciando...")
    app.run_polling()


if __name__ == "__main__":
    main()
