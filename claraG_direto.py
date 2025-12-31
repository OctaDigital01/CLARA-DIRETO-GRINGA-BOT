import asyncio
import os
from dataclasses import dataclass
from typing import Optional

from aiohttp import web
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    ApplicationBuilder,
    BusinessConnectionHandler,
    ChatJoinRequestHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ========================
# Configurações e modelos
# ========================


# Carrega variáveis de ambiente do .env local (se existir)
try:
    from dotenv import load_dotenv, find_dotenv  # type: ignore

    # Carrega .env padrão sem sobrescrever variáveis já definidas no ambiente
    load_dotenv(find_dotenv(), override=False)
    # Carrega .env.local (se existir) com override=True para facilitar ajustes locais
    load_dotenv(".env.local", override=True)
except Exception:
    pass


def _getenv(name: str) -> Optional[str]:
    return os.getenv(name)


@dataclass(frozen=True)
class Settings:
    token: str
    group_id: int


def _load_settings() -> Settings:
    token = _getenv("TELEGRAM_BOT_TOKEN") or ""
    raw_group_id = _getenv("ID_DO_GRUPO") or ""

    missing = []
    if not token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not raw_group_id:
        missing.append("ID_DO_GRUPO")
    if missing:
        raise RuntimeError("Variáveis faltando: " + ", ".join(missing))

    try:
        group_id = int(raw_group_id)
    except ValueError as exc:
        raise RuntimeError("ID_DO_GRUPO deve ser numérico (ex.: -1001234567890).") from exc

    return Settings(token=token, group_id=group_id)


SETTINGS = _load_settings()
COMBO_DISPATCHED_CHATS = set()


# ========================
# Utilidades de envio
# ========================


async def _handle_blocking_exception(user_id: Optional[int], exc: Exception) -> None:
    text = str(exc).lower()
    if any(x in text for x in ("blocked", "deactivated", "chat not found")):
        print(f"Usuário {user_id} bloqueou o bot ou chat indisponível.")


async def _safe_reply_text(
    message: Message,
    *,
    text: str,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    try:
        business_connection_id = getattr(message, "business_connection_id", None)
        return await message.reply_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
        )
    except TypeError:
        try:
            bot = None
            try:
                bot = message.get_bot()  # PTB >=20
            except Exception:
                bot = getattr(message, "bot", None) or getattr(message, "_bot", None)
            chat = getattr(message, "chat", None)
            chat_id = getattr(message, "chat_id", None) or (chat.id if chat else None)
            bcid = getattr(message, "business_connection_id", None)
            if bot and chat_id is not None:
                return await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    business_connection_id=bcid,
                )
        except TypeError:
            return None
        except Exception:
            return None
    except (Forbidden, BadRequest) as exc:
        await _handle_blocking_exception(getattr(message, "from_user", None) and message.from_user.id, exc)
        return None


async def _safe_send_message(
    bot,
    *,
    chat_id: int,
    user_id: Optional[int],
    text: str,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    business_connection_id: Optional[str] = None,
) -> Optional[Message]:
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            business_connection_id=business_connection_id,
        )
    except (Forbidden, BadRequest) as exc:
        await _handle_blocking_exception(user_id, exc)
        return None


async def _safe_delete_message(message: Optional[Message]) -> None:
    if not message:
        return
    try:
        await message.delete()
    except Exception:
        pass


async def _safe_delete_message_by_id(bot, chat_id: Optional[int], message_id: Optional[int]) -> None:
    if not bot or chat_id is None or message_id is None:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _safe_send_photo(
    bot,
    *,
    chat_id: int,
    user_id: Optional[int],
    photo,
    caption: Optional[str] = None,
    parse_mode: Optional[str] = None,
    business_connection_id: Optional[str] = None,
):
    try:
        return await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
            business_connection_id=business_connection_id,
        )
    except (Forbidden, BadRequest) as exc:
        await _handle_blocking_exception(user_id, exc)
        return None


async def _safe_send_video(
    bot,
    *,
    chat_id: int,
    user_id: Optional[int],
    video,
    caption: Optional[str] = None,
    parse_mode: Optional[str] = None,
    business_connection_id: Optional[str] = None,
):
    try:
        return await bot.send_video(
            chat_id=chat_id,
            video=video,
            caption=caption,
            parse_mode=parse_mode,
            business_connection_id=business_connection_id,
        )
    except (Forbidden, BadRequest) as exc:
        await _handle_blocking_exception(user_id, exc)
        return None


async def _safe_send_audio(
    bot,
    *,
    chat_id: int,
    user_id: Optional[int],
    audio,
    caption: Optional[str] = None,
    parse_mode: Optional[str] = None,
    business_connection_id: Optional[str] = None,
):
    try:
        return await bot.send_audio(
            chat_id=chat_id,
            audio=audio,
            caption=caption,
            parse_mode=parse_mode,
            business_connection_id=business_connection_id,
        )
    except (Forbidden, BadRequest) as exc:
        await _handle_blocking_exception(user_id, exc)
        return None


async def _safe_send_voice_prefer(
    bot,
    *,
    chat_id: int,
    user_id: Optional[int],
    voice,
    caption: Optional[str] = None,
    parse_mode: Optional[str] = None,
    business_connection_id: Optional[str] = None,
):
    try:
        return await bot.send_voice(
            chat_id=chat_id,
            voice=voice,
            caption=caption,
            parse_mode=parse_mode,
            business_connection_id=business_connection_id,
        )
    except (Forbidden, BadRequest) as exc:
        try:
            if isinstance(voice, str):
                tg_file = await bot.get_file(voice)
                file_path = getattr(tg_file, "file_path", None)
                if file_path:
                    file_url = f"https://api.telegram.org/file/bot{SETTINGS.token}/{str(file_path).lstrip('/')}"
                    try:
                        return await bot.send_voice(
                            chat_id=chat_id,
                            voice=file_url,
                            caption=caption,
                            parse_mode=parse_mode,
                            business_connection_id=business_connection_id,
                        )
                    except (Forbidden, BadRequest):
                        pass
        except Exception:
            pass
        try:
            return await bot.send_audio(
                chat_id=chat_id,
                audio=voice,
                caption=caption,
                parse_mode=parse_mode,
                business_connection_id=business_connection_id,
            )
        except (Forbidden, BadRequest) as exc2:
            await _handle_blocking_exception(user_id, exc2)
            return None


async def _safe_send_media_group(
    bot,
    *,
    chat_id: int,
    user_id: Optional[int],
    media: list,
    business_connection_id: Optional[str] = None,
):
    try:
        return await bot.send_media_group(
            chat_id=chat_id,
            media=media,
            business_connection_id=business_connection_id,
        )
    except (Forbidden, BadRequest) as exc:
        await _handle_blocking_exception(user_id, exc)
        return None


# ========================
# Conteúdo Beatriz (mídias)
# ========================


# IDs de mídia Beatriz
BEATRIZ_COMBO_FOTO_1 = _getenv("BEATRIZ_COMBO_FOTO_1")
BEATRIZ_COMBO_FOTO_2 = _getenv("BEATRIZ_COMBO_FOTO_2")
BEATRIZ_COMBO_FOTO_3 = _getenv("BEATRIZ_COMBO_FOTO_3")
BEATRIZ_COMBO_FOTO_4 = _getenv("BEATRIZ_COMBO_FOTO_4")
BEATRIZ_COMBO_FOTO_5 = _getenv("BEATRIZ_COMBO_FOTO_5")
BEATRIZ_COMBO_FOTO_6 = _getenv("BEATRIZ_COMBO_FOTO_6")
BEATRIZ_COMBO_FOTO_7 = _getenv("BEATRIZ_COMBO_FOTO_7")
BEATRIZ_COMBO_FOTO_8 = _getenv("BEATRIZ_COMBO_FOTO_8")
BEATRIZ_COMBO_FOTO_9 = _getenv("BEATRIZ_COMBO_FOTO_9")
BEATRIZ_COMBO_FOTO_10 = _getenv("BEATRIZ_COMBO_FOTO_10")

BEATRIZ_COMBO_VIDEO_1 = _getenv("BEATRIZ_COMBO_VIDEO_1")
BEATRIZ_COMBO_VIDEO_2 = _getenv("BEATRIZ_COMBO_VIDEO_2")
BEATRIZ_COMBO_VIDEO_3 = _getenv("BEATRIZ_COMBO_VIDEO_3")
BEATRIZ_COMBO_VIDEO_4 = _getenv("BEATRIZ_COMBO_VIDEO_4")

AUDIO_ENTREGA_COMBO = _getenv("AUDIO_ENTREGA_COMBO")
AUDIO_POS_ENTREGA_COMBO = _getenv("AUDIO_POS_ENTREGA_COMBO")
AUDIO_OFERTANDO_UPSELL = _getenv("AUDIO_OFERTANDO_UPSELL")
VIDEO_PREVIA_VIP = _getenv("VIDEO_PREVIA_VIP")
AUDIO_REMARKETING_UPSELL = _getenv("AUDIO_REMARKETING_UPSELL")
AUDIO_REMARKETING_UPSELL_2 = _getenv("AUDIO_REMARKETING_UPSELL_2")


# ========================
# Config VIP / Links
# ========================


VIP_LINK_1_MES = "https://global.tribopay.com.br/jvvo3"
VIP_LINK_6_MESES = "https://global.tribopay.com.br/kgwjs"
VIP_LINK_1_ANO = "https://global.tribopay.com.br/1fhtd"
EU_QUERO_LINK = "https://global.tribopay.com.br/zjvj6"

AUTO_REPLY_DELAY_SECONDS = 30
VIP_OFFER_DELAY_SECONDS = 180
GROUP_CHECK_INTERVAL_SECONDS = 60
GROUP_CHECK_MAX_ATTEMPTS = 5
GROUP_APPROVED_MESSAGE = "Te aceitei no grupo, espero que goste"


async def _combo_delivery_beatriz_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = getattr(context, "job", None)
    data = job.data if job else {}
    if not isinstance(data, dict):
        return
    chat_id = data.get("chat_id")
    user_id = data.get("user_id")
    bcid = data.get("business_connection_id")
    if not chat_id:
        return
    bot = context.application.bot
    await _safe_send_message(
        bot,
        chat_id=chat_id,
        user_id=user_id,
        text="Hi, sorry for the delay. I'll send everything",
        business_connection_id=bcid,
    )
    if AUDIO_ENTREGA_COMBO:
        await _safe_send_voice_prefer(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            voice=AUDIO_ENTREGA_COMBO,
            business_connection_id=bcid,
        )
    photos_ids = [
        BEATRIZ_COMBO_FOTO_1,
        BEATRIZ_COMBO_FOTO_2,
        BEATRIZ_COMBO_FOTO_3,
        BEATRIZ_COMBO_FOTO_4,
        BEATRIZ_COMBO_FOTO_5,
        BEATRIZ_COMBO_FOTO_6,
        BEATRIZ_COMBO_FOTO_7,
        BEATRIZ_COMBO_FOTO_8,
        BEATRIZ_COMBO_FOTO_9,
        BEATRIZ_COMBO_FOTO_10,
    ]
    photos = [pid for pid in photos_ids if pid]
    if len(photos) >= 2:
        media = [InputMediaPhoto(media=pid) for pid in photos]
        await _safe_send_media_group(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            media=media,
            business_connection_id=bcid,
        )
    elif len(photos) == 1:
        await _safe_send_photo(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            photo=photos[0],
            business_connection_id=bcid,
        )
    videos_ids = [
        BEATRIZ_COMBO_VIDEO_1,
        BEATRIZ_COMBO_VIDEO_2,
        BEATRIZ_COMBO_VIDEO_3,
        BEATRIZ_COMBO_VIDEO_4,
    ]
    videos = [vid for vid in videos_ids if vid]
    if len(videos) >= 2:
        media_v = [InputMediaVideo(media=vid) for vid in videos]
        await _safe_send_media_group(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            media=media_v,
            business_connection_id=bcid,
        )
    elif len(videos) == 1:
        await _safe_send_video(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            video=videos[0],
            business_connection_id=bcid,
        )
    if AUDIO_POS_ENTREGA_COMBO:
        await _safe_send_voice_prefer(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            voice=AUDIO_POS_ENTREGA_COMBO,
            business_connection_id=bcid,
        )
    else:
        await _safe_send_message(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            text="Depois que olhar, me fala se gostou, tá bom? 🤍",
            business_connection_id=bcid,
        )
    jobq = getattr(context, "job_queue", None)
    if jobq:
        jobq.run_once(
            _upsell_sequence_job,
            when=VIP_OFFER_DELAY_SECONDS,
            data={
                "chat_id": chat_id,
                "user_id": user_id,
                "business_connection_id": bcid,
            },
            name=f"upsell:beatriz:{chat_id}",
        )


async def _upsell_sequence_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = getattr(context, "job", None)
    data = job.data if job else {}
    if not isinstance(data, dict):
        return
    chat_id = data.get("chat_id")
    user_id = data.get("user_id")
    bcid = data.get("business_connection_id")
    if not chat_id:
        return
    bot = context.application.bot
    if AUDIO_OFERTANDO_UPSELL:
        await _safe_send_voice_prefer(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            voice=AUDIO_OFERTANDO_UPSELL,
            business_connection_id=bcid,
        )
    if VIDEO_PREVIA_VIP:
        await _safe_send_video(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            video=VIDEO_PREVIA_VIP,
            business_connection_id=bcid,
        )
    upsell_text = (
        "Look at this little preview I sent you 🥰\n"
        "Babe, what you really want is inside my VIP, look at everything you can see:\n\n"
        "💎 Videos and photos just the way you like them...\n"
        "💎 Exclusive videos for you, making you cum just the two of us\n"
        "💎 My personal contact\n"
        "💎 I always post new things\n"
        "💎 And much more my dear...\n\n"
        "Now choose a VIP option so you can see me in the best way and cumming for me 💦"
    )
    await _safe_send_message(
        bot,
        chat_id=chat_id,
        user_id=user_id,
        text=upsell_text,
        business_connection_id=bcid,
    )
    vip_keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("[$10]1 MONTH🔥", url=VIP_LINK_1_MES)],
            [InlineKeyboardButton("[$17]6 MONTHS+SURPRISE👀🔥", url=VIP_LINK_6_MESES)],
            [InlineKeyboardButton("[$20]1 YEAR+EXCLUSIVE VIDEO+🎁", url=VIP_LINK_1_ANO)],
        ]
    )
    await _safe_send_message(
        bot,
        chat_id=chat_id,
        user_id=user_id,
        text="Choose your VIP below 👇",
        reply_markup=vip_keyboard,
        business_connection_id=bcid,
    )
    jobq = getattr(context, "job_queue", None)
    if jobq and user_id:
        jobq.run_repeating(
            _group_check_job,
            interval=GROUP_CHECK_INTERVAL_SECONDS,
            first=GROUP_CHECK_INTERVAL_SECONDS,
            name=f"group_check:{chat_id}",
            data={
                "chat_id": chat_id,
                "user_id": user_id,
                "business_connection_id": bcid,
                "attempt": 0,
            },
        )


async def _send_remarketing(
    bot,
    *,
    chat_id: int,
    user_id: Optional[int],
    business_connection_id: Optional[str],
) -> None:
    if AUDIO_REMARKETING_UPSELL:
        await _safe_send_voice_prefer(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            voice=AUDIO_REMARKETING_UPSELL,
            business_connection_id=business_connection_id,
        )
    desc_text = (
        "Okay babe, I've already applied the discount for you 😘\n"
        "Take advantage now, because I'll delete this message later, just click here 👇"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("I WANT THIS 🔥", url=EU_QUERO_LINK)]])
    await _safe_send_message(
        bot,
        chat_id=chat_id,
        user_id=user_id,
        text=desc_text,
        reply_markup=keyboard,
        business_connection_id=business_connection_id,
    )
    if AUDIO_REMARKETING_UPSELL_2:
        try:
            await asyncio.sleep(45)
        except Exception:
            return
        await _safe_send_voice_prefer(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            voice=AUDIO_REMARKETING_UPSELL_2,
            business_connection_id=business_connection_id,
        )


async def _group_check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = getattr(context, "job", None)
    data = job.data if job else {}
    if not isinstance(data, dict):
        return
    chat_id = data.get("chat_id")
    user_id = data.get("user_id")
    bcid = data.get("business_connection_id")
    attempt = int(data.get("attempt", 0)) + 1
    data["attempt"] = attempt
    if job:
        job.data = data
    if not chat_id or not user_id:
        if job:
            job.schedule_removal()
        return
    bot = context.application.bot
    is_member = False
    try:
        member = await bot.get_chat_member(chat_id=SETTINGS.group_id, user_id=user_id)
        status = getattr(member, "status", None)
        is_member = status in {"member", "administrator", "creator"} or bool(getattr(member, "is_member", False))
    except Forbidden:
        return
    except BadRequest:
        is_member = False
    except Exception:
        is_member = False

    if is_member:
        await _safe_send_message(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            text=GROUP_APPROVED_MESSAGE,
            business_connection_id=bcid,
        )
        if job:
            job.schedule_removal()
        return

    if attempt >= GROUP_CHECK_MAX_ATTEMPTS:
        if job:
            job.schedule_removal()
        await _send_remarketing(
            bot,
            chat_id=chat_id,
            user_id=user_id,
            business_connection_id=bcid,
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    chat = update.effective_chat
    user = update.effective_user
    if not chat:
        return
    try:
        from_user = getattr(message, "from_user", None)
        if from_user is not None and getattr(from_user, "is_bot", False):
            return
    except Exception:
        pass
    try:
        is_private = getattr(chat, "type", None) == "private"
        chat_id = getattr(chat, "id", None)
        if not is_private or chat_id is None:
            return
        already_dispatched = bool(context.chat_data.get("combo_dispatched")) or (chat_id in COMBO_DISPATCHED_CHATS)
        if already_dispatched:
            return
        context.chat_data["combo_dispatched"] = True
        if chat_id is not None:
            COMBO_DISPATCHED_CHATS.add(chat_id)
    except Exception:
        return
    bcid = getattr(message, "business_connection_id", None)
    if bcid:
        context.chat_data["business_connection_id"] = bcid
    job_queue = getattr(context, "job_queue", None)
    if not job_queue:
        await asyncio.sleep(AUTO_REPLY_DELAY_SECONDS)
        await _safe_reply_text(message, text="Hi, sorry for the delay. I'll send everything.")
        return
    job_queue.run_once(
        _combo_delivery_beatriz_job,
        when=AUTO_REPLY_DELAY_SECONDS,
        data={
            "chat_id": chat.id,
            "user_id": user.id if user else None,
            "business_connection_id": bcid,
        },
        name=f"auto_reply:beatriz:{chat.id}:{getattr(message, 'message_id', 'x')}",
    )


async def business_connection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = getattr(update, "business_connection", None)
    if not conn:
        return
    try:
        status = "conectado" if getattr(conn, "is_enabled", False) else "desconectado"
        print(f"Business connection {conn.id}: {status}")
    except Exception:
        pass


async def handle_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    trigger_text = (getattr(message, "caption", None) or getattr(message, "text", None) or "").strip().lower()
    if "file_id" not in trigger_text:
        return

    replies = []
    if message.document:
        replies.append(f"Documento: {message.document.file_id}")
    if message.photo:
        replies.append(f"Foto: {message.photo[-1].file_id}")
    if message.video:
        replies.append(f"Vídeo: {message.video.file_id}")
    if message.audio:
        replies.append(f"Áudio: {message.audio.file_id}")
    if message.voice:
        replies.append(f"Voice: {message.voice.file_id}")
    if message.animation:
        replies.append(f"GIF: {message.animation.file_id}")

    if replies:
        await _safe_reply_text(message, text="\n".join(replies))


async def handle_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    join_request = getattr(update, "chat_join_request", None)
    if not join_request:
        return
    chat = getattr(join_request, "chat", None)
    chat_id = getattr(chat, "id", None)
    if chat_id != SETTINGS.group_id:
        return
    try:
        await join_request.approve()
        print(f"Join request aprovado para user_id={join_request.from_user.id}")
    except Exception as exc:
        print(f"Falha ao aprovar join request: {exc}")


# ========================
# Webhook / Healthcheck
# ========================


async def _healthcheck_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


# --- Handlers de Webhook do Telegram ---
async def _telegram_update_handler(request: web.Request) -> web.Response:
    application: Application = request.app["telegram_application"]
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
    try:
        update = Update.de_json(data, application.bot)
        await application.update_queue.put(update)
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_update"}, status=400)
    return web.json_response({"ok": True})


# ========================
# Bootstrap
# ========================


def _build_application() -> Application:
    app = ApplicationBuilder().token(SETTINGS.token).build()
    app.add_handler(BusinessConnectionHandler(business_connection_handler))
    app.add_handler(ChatJoinRequestHandler(handle_chat_join_request))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE, handle_text_message))
    app.add_handler(MessageHandler(filters.ATTACHMENT, handle_attachment))
    return app


def _build_web_app(application: Application) -> web.Application:
    web_app = web.Application()
    web_app["telegram_application"] = application
    web_app.router.add_get("/healthz", _healthcheck_handler)
    webhook_path = os.getenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook")
    web_app.router.add_post(webhook_path, _telegram_update_handler)
    return web_app


async def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    application = _build_application()
    web_app = _build_web_app(application)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()

    await application.initialize()

    webhook_base = os.getenv("TELEGRAM_WEBHOOK_URL")
    if not webhook_base:
        rw_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_URL")
        if rw_domain:
            if not rw_domain.startswith("http"):
                webhook_base = f"https://{rw_domain}"
            else:
                webhook_base = rw_domain
    webhook_path = os.getenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook")
    try:
        if webhook_base:
            full_webhook_url = f"{webhook_base.rstrip('/')}{webhook_path}"
            await application.bot.set_webhook(
                url=full_webhook_url,
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )
            await application.start()
            try:
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass
        else:
            try:
                await application.bot.delete_webhook(drop_pending_updates=True)
            except Exception:
                pass
            await application.start()
            try:
                await application.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass
    finally:
        try:
            if application.updater:
                await application.updater.stop()
        except Exception:
            pass
        try:
            await application.stop()
        except Exception:
            pass
        try:
            await application.shutdown()
        except Exception:
            pass
        try:
            await runner.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
