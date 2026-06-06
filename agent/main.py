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
from users import get_pipedrive_key, is_allowed, set_pipedrive_key

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
    "Primeiro, registre sua chave Pipedrive:\n"
    "`/minha\\_chave SUA\\_CHAVE\\_AQUI`\n\n"
    "Use /novo para reiniciar a conversa.\n"
    "Use /meu\\_id para ver seu ID do Telegram."
)


def _user_is_authorized(user_id: int) -> bool:
    return is_allowed(user_id)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _user_is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Acesso não autorizado.")
        return
    await update.message.reply_text(BOAS_VINDAS, parse_mode="Markdown")


async def cmd_novo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _user_is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Acesso não autorizado.")
        return
    agent.clear_history(update.effective_chat.id)
    await update.message.reply_text("Conversa reiniciada! Como posso ajudar?")


async def cmd_meu_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Seu ID no Telegram: `{update.effective_user.id}`",
        parse_mode="Markdown",
    )


async def cmd_minha_chave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _user_is_authorized(user_id):
        await update.message.reply_text("⛔ Acesso não autorizado.")
        return

    if not context.args:
        await update.message.reply_text(
            "Informe sua chave Pipedrive:\n"
            "`/minha\\_chave SUA\\_CHAVE\\_AQUI`\n\n"
            "Encontre em: Pipedrive → Configurações → Preferências pessoais → API",
            parse_mode="Markdown",
        )
        return

    key = context.args[0]
    set_pipedrive_key(user_id, key)
    await update.message.reply_text("Chave Pipedrive registrada! Pode começar a perguntar.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not _user_is_authorized(user_id):
        await update.message.reply_text("⛔ Acesso não autorizado.")
        return

    pipedrive_key = get_pipedrive_key(user_id)
    if not pipedrive_key:
        await update.message.reply_text(
            "Você ainda não registrou sua chave Pipedrive.\n"
            "Use: `/minha\\_chave SUA\\_CHAVE\\_AQUI`",
            parse_mode="Markdown",
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        response = await agent.chat(chat_id, update.message.text, pipedrive_key)
        for chunk in _split_message(response):
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(chunk)
    except Exception:
        logger.exception("Erro ao processar mensagem do chat_id=%s", chat_id)
        await update.message.reply_text("Ocorreu um erro. Tente novamente.")


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado no .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("novo", cmd_novo))
    app.add_handler(CommandHandler("meu_id", cmd_meu_id))
    app.add_handler(CommandHandler("minha_chave", cmd_minha_chave))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot iniciando...")
    app.run_polling()


if __name__ == "__main__":
    main()
