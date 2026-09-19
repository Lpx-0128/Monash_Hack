"""Hermes native Telegram extension. No model tools and no independent update consumer."""
import asyncio
import base64
import io
import json
import os
import sqlite3
from pathlib import Path

PIN = "44945d224c2ccd6e0a55f16223c7ab0dd39331bf"

def register(ctx):
    ctx.register_platform_handler("telegram", wire)

def wire(application, adapter):
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

    async def receive(update, context):
        user, message = update.effective_user, update.effective_message
        if user and message and not user.is_bot:
            actor, chat = str(user.id), str(message.chat_id)
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
        app.router.add_post("/send", send)
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
            db.close()
    application.bot_data['shipping_task'] = asyncio.create_task(run(), name="shipping-review-bridge")
