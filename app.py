import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.error import TelegramError, Forbidden
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

# ── Env ────────────────────────────────────────────────────────────────────────
load_dotenv("stack.env", override=False)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("deleter-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET_CHAT_ID_RAW = os.getenv("TARGET_CHAT_ID")
BLOCKED_USER_ID = int(os.getenv("BLOCKED_USER_ID", "329047005"))

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден (stack.env или ENV).")
if not TARGET_CHAT_ID_RAW:
    raise RuntimeError("❌ TARGET_CHAT_ID не найден (stack.env или ENV).")
TARGET_CHAT_ID = int(TARGET_CHAT_ID_RAW)


# ── Handlers ──────────────────────────────────────────────────────────────────
async def purge_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Удаляем сообщения от BLOCKED_USER_ID. Максимально подробные логи."""
    msg = update.effective_message
    if not msg:
        return

    user = msg.from_user
    if user is None:
        # Это бывает, если прилетел channel_post и т.п.
        log.warning(
            "📣 Получен update без from_user (msg_id=%s, chat_id=%s). "
            "В каналах нельзя фильтровать по user_id; используйте обсуждение (supergroup).",
            getattr(msg, "message_id", None),
            getattr(msg, "chat_id", None),
        )
        return

    log.debug(
        "К удалению: chat_id=%s, msg_id=%s, from_user_id=%s (%s), text=%r",
        msg.chat_id,
        msg.message_id,
        user.id,
        user.full_name,
        getattr(msg, "text", None),
    )

    try:
        await msg.delete()
        log.info(
            "✅ Удалено сообщение %s от user_id=%s в чате %s",
            msg.message_id,
            user.id,
            msg.chat_id,
        )
    except Forbidden as e:
        log.error(
            "❌ Forbidden при удалении (нет прав Delete messages / бот не админ?). Причина: %s",
            e,
        )
    except TelegramError as e:
        log.error("❌ TelegramError при удалении msg_id=%s: %s", msg.message_id, e)
    except Exception as e:
        log.exception("❌ Неизвестная ошибка при удалении msg_id=%s: %s", msg.message_id, e)


async def log_every_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Неблокирующий лог всех сообщений в целевом чате."""
    msg = update.effective_message
    if not msg:
        return
    user = msg.from_user
    log.info(
        "📩 Вижу сообщение: chat_id=%s, msg_id=%s, from_user_id=%s (%s), text=%r",
        msg.chat_id,
        msg.message_id,
        getattr(user, "id", None),
        getattr(user, "full_name", None),
        getattr(msg, "text", None),
    )


async def startup_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """При старте: лог информации о боте, типе чата, правах и linked_chat_id."""
    bot = context.bot
    try:
        me = await bot.get_me()
        log.info("🤖 Я бот: @%s (id=%s)", me.username, me.id)
    except Exception as e:
        log.error("Не удалось получить сведения о боте: %s", e)

    try:
        chat = await bot.get_chat(TARGET_CHAT_ID)
        log.info("🔎 Проверяю чат: title=%r, type=%s, id=%s", chat.title, chat.type, chat.id)

        # Подсказка для каналов: обсуждение (supergroup)
        linked_chat_id = getattr(chat, "linked_chat_id", None)
        if linked_chat_id:
            log.warning(
                "ℹ️ У чата есть linked_chat_id=%s (обычно обсуждение канала). "
                "Для фильтра по user_id используйте именно его как TARGET_CHAT_ID.",
                linked_chat_id,
            )
    except Exception as e:
        log.error("Не удалось получить чат %s: %s", TARGET_CHAT_ID, e)
        return

    try:
        member = await bot.get_chat_member(TARGET_CHAT_ID, (await bot.get_me()).id)
        status = getattr(member, "status", None)
        can_delete = getattr(member, "can_delete_messages", None)
        can_restrict = getattr(member, "can_restrict_members", None)
        log.info(
            "👮 Права бота: status=%s, can_delete_messages=%s, can_restrict_members=%s",
            status,
            can_delete,
            can_restrict,
        )

        if status not in ("administrator", "creator"):
            log.warning("⚠️ Бот НЕ администратор. Назначьте админом и включите 'Delete messages'.")
        elif can_delete is False:
            log.warning("⚠️ У бота нет права 'Удалять сообщения'. Включите его.")
        else:
            log.info("✅ Права выглядят корректно.")
    except Exception as e:
        log.error("Не удалось проверить права бота: %s", e)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("🚨 Необработанная ошибка: %s", context.error)


# ── App ────────────────────────────────────────────────────────────────────────
def main() -> None:
    # Важно: для JobQueue требуется установка:  pip install "python-telegram-bot[job-queue]"
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 0-я группа — СНАЧАЛА удаляем целевого пользователя
    app.add_handler(
        MessageHandler(
            filters.Chat(TARGET_CHAT_ID) & filters.User(user_id=BLOCKED_USER_ID),
            purge_user_message,
        ),
        group=0,
    )

    # 1-я группа — затем логируем всё и НЕ блокируем
    app.add_handler(
        MessageHandler(
            filters.Chat(TARGET_CHAT_ID),
            log_every_message,
            block=False,
        ),
        group=1,
    )

    app.add_error_handler(error_handler)

    # Проверка прав через секунду после старта (если JobQueue установлен)
    if app.job_queue:
        app.job_queue.run_once(startup_check, when=1.0)
    else:
        log.warning(
            "ℹ️ JobQueue не инициализирован. Установите зависимость: "
            'pip install "python-telegram-bot[job-queue]" — иначе startup_check не выполнится автоматически.'
        )

    log.info(
        "🚀 Бот запущен. Чат: %s | Цель: удалить сообщения от user_id=%s",
        TARGET_CHAT_ID,
        BLOCKED_USER_ID,
    )
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
