"""Hermes native Telegram extension. No model tools and no independent update consumer."""
import asyncio
import base64
import io
import json
import os
import sqlite3
import inspect
import logging
from pathlib import Path

PIN = "44945d224c2ccd6e0a55f16223c7ab0dd39331bf"
_active_application = None
_active_task = None

def preserve_pending_updates(adapter):
    """Pinned, instance-local policy for the dedicated long-polling gateway.

    All polling generations (including conflict recovery) share this entry point.
    Never discard queued user decisions to take over a competing poller.
    """
    if os.environ.get('TELEGRAM_WEBHOOK_URL'):
        raise RuntimeError('Shipping pending-update policy requires long polling')
    if getattr(adapter, '_shipping_preserves_pending', False):
        return
    original = getattr(adapter, '_start_polling_once', None)
    if not callable(original) or 'drop_pending_updates' not in inspect.signature(original).parameters:
        raise RuntimeError('Pinned Hermes polling interface changed; compatibility verification required')
    async def preserving_start(app, *, drop_pending_updates, **kwargs):
        if drop_pending_updates:
            logging.getLogger(__name__).info('Shipping gateway preserves pending Telegram updates')
        return await original(app, drop_pending_updates=False, **kwargs)
    adapter._start_polling_once = preserving_start
    adapter._shipping_preserves_pending = True

def register(ctx):
    ctx.register_platform_handler("telegram", wire)

def wire(application, adapter):
    global _active_application, _active_task
    preserve_pending_updates(adapter)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import CallbackQueryHandler, MessageHandler, TypeHandler, ApplicationHandlerStop, filters
    from telegram import Update
    from aiohttp import web, ClientSession, ClientTimeout

    secret = os.environ["F2_BRIDGE_TOKEN"]
    if len(secret) < 32:
        raise RuntimeError("Shipping bridge credential not configured")
    home = Path(os.environ["HERMES_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(home / "shipping-inbound.sqlite")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS inbound (id TEXT PRIMARY KEY, payload TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS pairing (actor TEXT, chat TEXT, PRIMARY KEY(actor, chat))")
    allowed = {(x["actor"], x["chat"]) for x in json.loads(os.environ.get("F2_RECIPIENTS", "[]"))}
    public_enrollment = os.environ.get('HARBOR_HOSTED') == 'true'
    if public_enrollment:
        allowed.update((a, c) for a, c in db.execute('SELECT actor,chat FROM pairing') if a == c and a.isdigit())

    async def receive(update, context):
        if application is not _active_application:
            raise ApplicationHandlerStop
        user, message = update.effective_user, update.effective_message
        if user and message and not user.is_bot:
            actor, chat = str(user.id), str(message.chat_id)
            if public_enrollment and message.chat.type != 'private':
                raise ApplicationHandlerStop
            if public_enrollment and (actor, chat) not in allowed and message.text == '/start' and actor == chat and len(allowed) < 99:
                db.execute('INSERT OR IGNORE INTO pairing VALUES (?,?)', (actor,chat)); db.commit()
                allowed.add((actor,chat))
            if (actor, chat) not in allowed:
                # Only local IDs, no source access or outbound contact before explicit designation.
                if message.text == "/start" and message.chat.type == "private":
                    db.execute("INSERT OR IGNORE INTO pairing VALUES (?,?)", (actor, chat)); db.commit()
                raise ApplicationHandlerStop
            payload = {"id": str(update.update_id), "actor": actor, "chat": chat, "message": str(message.message_id)}
            query = update.callback_query
            if query:
                payload["callback"] = query.data or ""
            elif message.text:
                payload["text"] = message.text[:8192]
                if message.reply_to_message:
                    payload["reply"] = str(message.reply_to_message.message_id)
            else:
                raise ApplicationHandlerStop
            db.execute("INSERT OR IGNORE INTO inbound(id,payload) VALUES (?,?)", (payload["id"], json.dumps(payload))); db.commit()
            if query:
                try: await query.answer("Review action received; checking current state.")
                except Exception: pass  # Durable queue, not callback toast, establishes receipt.
        raise ApplicationHandlerStop

    async def deny(update, context):
        raise ApplicationHandlerStop

    # Dedicated shipping profile: no incoming message falls through into general agent tools.
    application.add_handler(CallbackQueryHandler(receive, pattern=r"^ship:"), group=-100)
    application.add_handler(MessageHandler(filters.ALL, receive), group=-100)
    application.add_handler(TypeHandler(Update, deny), group=-100)

    async def run():
        while not application.running:
            await asyncio.sleep(.25)
        async def send(request):
            if request.headers.get("Authorization") != "Bearer " + secret:
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                body = await request.json()
                chat = str(body["chat"])
                if chat not in {c for _, c in allowed}:
                    return web.json_response({"error": "chat not authorized"}, status=403)
                if "message" in body:
                    from telegram.error import BadRequest
                    rows = [[InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row] for row in body.get("buttons", [])]
                    markup = InlineKeyboardMarkup(rows)
                    try:
                        if "text" in body:
                            await application.bot.edit_message_text(chat_id=chat, message_id=int(body["message"]), text=body["text"], reply_markup=markup, parse_mode=None)
                        else:
                            await application.bot.edit_message_reply_markup(chat_id=chat, message_id=int(body["message"]), reply_markup=markup)
                    except BadRequest as error:
                        if "message is not modified" not in str(error).lower(): raise
                    return web.json_response({"message": str(body["message"])})
                if "data" in body:
                    data = base64.b64decode(body["data"], validate=True)
                    if len(data) > 8_000_000: raise ValueError()
                    sent = await application.bot.send_document(chat_id=chat, document=io.BytesIO(data), filename=Path(body["filename"]).name, caption="Synthetic source document — simulated extraction and grounding.")
                else:
                    rows = [[InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row] for row in body.get("buttons", [])]
                    sent = await application.bot.send_message(chat_id=chat, text=body["text"], reply_markup=InlineKeyboardMarkup(rows) if rows else None, parse_mode=None)
                return web.json_response({"message": str(sent.message_id)})
            except Exception:
                return web.json_response({"error": "Telegram delivery unavailable"}, status=503)
        app = web.Application(client_max_size=12_000_000)
        async def health(request):
            return web.json_response({'status':'ok','interpretation_configured':os.environ.get('F3_ENABLED') == 'true' and bool(os.environ.get('F3_MODEL'))})
        app.router.add_get('/health', health)
        app.router.add_post("/send", send)
        interpreting = asyncio.Lock()
        db.execute('CREATE TABLE IF NOT EXISTS model_usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)')
        async def interpret_request(request):
            if request.headers.get('Authorization') != 'Bearer ' + secret:
                return web.json_response({'error':'unauthorized'}, status=401)
            if os.environ.get('F3_ENABLED') != 'true':
                return web.json_response({'error':'interpretation disabled'}, status=503)
            if interpreting.locked():
                return web.json_response({'error':'interpretation busy'}, status=429)
            try:
                if request.content_length is None or request.content_length > 16000:
                    return web.json_response({'error':'invalid context'}, status=400)
                payload=await request.json()
                from .interpretation import interpret
                async with interpreting:
                    from datetime import datetime, timezone
                    day = datetime.now(timezone.utc).date().isoformat()
                    row = db.execute('SELECT calls FROM model_usage WHERE day=?', (day,)).fetchone()
                    if row and row[0] >= int(os.environ.get('F3_DAILY_CALL_LIMIT', '200')):
                        return web.json_response({'error':'Daily interpretation limit reached; use structured review controls'}, status=429)
                    db.execute('INSERT INTO model_usage VALUES (?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1', (day,)); db.commit()
                    result=await asyncio.wait_for(asyncio.to_thread(interpret,payload), timeout=22)
                return web.json_response(result)
            except Exception:
                return web.json_response({'error':'Copilot interpretation unavailable; use review controls'}, status=503)
        app.router.add_post('/interpret', interpret_request)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            site = web.TCPSite(runner, "127.0.0.1", int(os.environ.get("F2_BRIDGE_PORT", "5175")))
            await site.start()
            application.bot_data['shipping_port'] = site._server.sockets[0].getsockname()[1]
            async with ClientSession(timeout=ClientTimeout(total=30)) as client:
                while application.running:
                    for identity, payload in db.execute("SELECT id,payload FROM inbound WHERE done=0 ORDER BY rowid LIMIT 20").fetchall():
                        try:
                            async with client.post("http://127.0.0.1:" + os.environ.get("F2_PORT", "5174") + "/update", data=payload, headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"}) as response:
                                if response.status == 200:
                                    db.execute("UPDATE inbound SET done=1 WHERE id=?", (identity,)); db.commit()
                                else: break
                        except Exception: break
                    await asyncio.sleep(1)
        finally:
            await runner.cleanup()
    previous = _active_task
    _active_application = application
    async def own_bridge():
        try:
            # Hermes can abandon an application whose network shutdown hung.
            # Release its local port/queue before the replacement takes ownership.
            if previous and not previous.done():
                previous.cancel()
                try:
                    await previous
                except asyncio.CancelledError:
                    pass
            await run()
        finally:
            db.close()
    _active_task = asyncio.create_task(own_bridge(), name="shipping-review-bridge")
    application.bot_data['shipping_task'] = _active_task
