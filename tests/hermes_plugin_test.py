"""Actual pinned Hermes registration and PTB dispatch; Telegram HTTP is a test double."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import sys
from contextlib import closing
from types import SimpleNamespace
from aiohttp import web, ClientSession
from telegram import Update
from telegram.ext import Application, TypeHandler
from telegram.request import BaseRequest
from hermes_cli.plugins import PluginManager, PluginManifest

ROOT = Path(__file__).resolve().parents[1]

class TelegramDouble(BaseRequest):
    @property
    def read_timeout(self): return 5
    def __init__(self): self.calls=[]
    async def initialize(self): pass
    async def shutdown(self): pass
    async def do_request(self, url, method, request_data=None, **kwargs):
        action=url.rsplit('/',1)[-1]
        params=request_data.parameters if request_data else {}
        self.calls.append((action,params))
        if action=='getMe': result={'id':999,'is_bot':True,'first_name':'Synthetic test','username':'synthetic_test_bot'}
        elif action=='answerCallbackQuery':result=True
        else:result={'message_id':len(self.calls),'date':0,'chat':{'id':101,'type':'private'},'text':params.get('text','')}
        return 200,json.dumps({'ok':True,'result':result}).encode()

async def main():
    with tempfile.TemporaryDirectory(prefix='hermes-f2-test-') as tmp:
        os.environ.update(HERMES_HOME=tmp,F2_BRIDGE_TOKEN='test-bridge-secret-000000000000000000',F2_RECIPIENTS=json.dumps([{'actor':'101','chat':'101'}]),F2_BRIDGE_PORT='0')
        received=[]
        unavailable=False
        async def update(request):
            if unavailable:return web.json_response({'error':'injected outage'},status=503)
            received.append(await request.json());return web.json_response({'ok':True})
        service=web.Application();service.router.add_post('/update',update);runner=web.AppRunner(service);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();os.environ['F2_PORT']=str(site._server.sockets[0].getsockname()[1])
        manager=PluginManager()
        manager._load_plugin(PluginManifest(name='shipping-review',version='0.1.0',source='user',path=str(ROOT/'hermes/shipping-review')))
        factories=manager.get_platform_handler_factories('telegram')
        assert len(factories)==1, 'Hermes must load and register the real plugin'
        fallback=[]
        async def forbidden_fallback(u,c):fallback.append(u.update_id)
        request=TelegramDouble();app=Application.builder().token('999:synthetic-test-token').request(request).build()
        await app.initialize()
        polling_calls=[]
        async def start_polling_once(app, *, drop_pending_updates, **kwargs):
            polling_calls.append((app,drop_pending_updates,kwargs))
            return 'generation-preserved'
        adapter=SimpleNamespace(_start_polling_once=start_polling_once)
        factory,_=factories[0];factory(app,adapter)
        policy=sys.modules[factory.__module__].preserve_pending_updates
        wrapped=adapter._start_polling_once
        policy(adapter)
        assert adapter._start_polling_once is wrapped, 'Do not stack wrappers on application rebuild'
        try: policy(SimpleNamespace())
        except RuntimeError: pass
        else: raise AssertionError('Unknown polling interface must fail compatibility checks')
        os.environ['TELEGRAM_WEBHOOK_URL']='https://synthetic.example/webhook'
        try:
            try: policy(SimpleNamespace(_start_polling_once=start_polling_once))
            except RuntimeError: pass
            else: raise AssertionError('Unverified webhook mode must not silently bypass policy')
        finally: os.environ.pop('TELEGRAM_WEBHOOK_URL')
        for requested in [True,False,True]:  # cold boot, reconnect, conflict recovery
            result=await adapter._start_polling_once(app,drop_pending_updates=requested,error_callback=None,schedule_verifier=False)
            assert result=='generation-preserved'
        assert all(not call[1] for call in polling_calls)
        assert all(call[2]=={'error_callback':None,'schedule_verifier':False} for call in polling_calls)
        app.add_handler(TypeHandler(Update,forbidden_fallback))
        await app.start()
        def event(i,actor=101,text='21707',reply=77,callback=None):
            message={'message_id':88,'date':0,'chat':{'id':actor,'type':'private'},'from':{'id':actor,'is_bot':False,'first_name':'Test'},'text':text}
            if reply:message['reply_to_message']={'message_id':reply,'date':0,'chat':message['chat'],'text':'Synthetic review'}
            raw={'update_id':i,'message':message} if callback is None else {'update_id':i,'callback_query':{'id':'callback-'+str(i),'chat_instance':'test','from':message['from'],'message':message,'data':callback}}
            return Update.de_json(raw,app.bot)
        await app.process_update(event(1));await app.process_update(event(1));await app.process_update(event(2,callback='ship:opaque'))
        await app.process_update(event(3,actor=202,text='/start'));await app.process_update(event(4,actor=202,callback='ship:opaque'))
        await app.process_update(event(5,text='/reset',reply=None))
        for _ in range(40):
            if len(received)>=3:break
            await asyncio.sleep(.1)
        assert not fallback,'Shipping profile must never fall through to model or generic command handlers'
        assert len(received)==3,received
        assert received[0]['actor']=='101' and received[0]['chat']=='101' and received[0]['reply']=='77'
        assert received[1]['callback']=='ship:opaque' and received[1]['message']=='88'
        assert sum(x['id']=='1' for x in received)==1,'SQLite deduplicates incoming updates'
        with closing(sqlite3.connect(Path(tmp)/'shipping-inbound.sqlite')) as db:
            assert db.execute('SELECT actor,chat FROM pairing').fetchall()==[('202','202')]
            assert db.execute('SELECT COUNT(*) FROM inbound WHERE done=1').fetchone()[0]==3
        port=app.bot_data['shipping_port']
        async with ClientSession() as client:
            url=f'http://127.0.0.1:{port}/send'
            headers={'Authorization':'Bearer '+os.environ['F2_BRIDGE_TOKEN']}
            async with client.post(url,json={'chat':'101','text':'Synthetic review','buttons':[[{'text':'Confirm','callback_data':'ship:opaque'}]]},headers=headers) as r:assert r.status==200 and (await r.json())['message']
            async with client.post(url,json={'chat':'101','filename':'synthetic.txt','data':'U1lOVEhFVElD'},headers=headers) as r:assert r.status==200
            async with client.post(url,json={'chat':'202','text':'must not send'},headers=headers) as r:assert r.status==403
            async with client.post(url,json={'chat':'101','text':'must not send'}) as r:assert r.status==401
        assert any(a=='sendDocument' for a,_ in request.calls)
        assert any(a=='sendMessage' and 'reply_markup' in p for a,p in request.calls)
        assert not any(a=='getUpdates' for a,_ in request.calls),'Plugin must not create a Telegram update consumer'
        unavailable=True
        await app.process_update(event(6,text='pending during outage'))
        await asyncio.sleep(1.1)
        assert len(received)==3
        await app.stop();await app.bot_data['shipping_task'];await app.shutdown()
        # Gateway application recreated with the same independent shipping SQLite store.
        app=Application.builder().token('999:synthetic-test-token').request(TelegramDouble()).build()
        await app.initialize();factory(app,SimpleNamespace(_start_polling_once=start_polling_once));await app.start();unavailable=False
        for _ in range(40):
            if len(received)==4:break
            await asyncio.sleep(.1)
        assert received[-1]['id']=='6' and len(received)==4,'Unforwarded received update survives gateway restart'
        await app.process_update(event(6,text='duplicate after restart'));await asyncio.sleep(1.1)
        assert len(received)==4
        # Recovery may abandon an application that still reports running.
        old_app=app
        old_calls=len(old_app.bot.request.calls)
        os.environ['F2_BRIDGE_PORT']=str(old_app.bot_data['shipping_port'])
        replacement_request=TelegramDouble()
        app=Application.builder().token('999:synthetic-test-token').request(replacement_request).build()
        await app.initialize();factory(app,SimpleNamespace(_start_polling_once=start_polling_once));await app.start()
        for _ in range(40):
            if 'shipping_port' in app.bot_data:break
            await asyncio.sleep(.1)
        assert app.bot_data['shipping_port']==old_app.bot_data['shipping_port'], 'Replacement must reclaim the same bridge port'
        assert old_app.bot_data['shipping_task'].cancelled()
        async with ClientSession() as client:
            async with client.post(f"http://127.0.0.1:{app.bot_data['shipping_port']}/send",json={'chat':'101','text':'Recovered'},headers=headers) as r:assert r.status==200
        assert any(a=='sendMessage' for a,_ in replacement_request.calls)
        assert len(old_app.bot.request.calls)==old_calls, 'Never deliver through abandoned application'
        await old_app.process_update(event(7,text='abandoned generation'))
        await app.process_update(event(8,text='replacement generation'))
        for _ in range(40):
            if len(received)==5:break
            await asyncio.sleep(.1)
        assert received[-1]['id']=='8' and len(received)==5
        await old_app.stop();await old_app.shutdown()
        await app.stop();await app.bot_data['shipping_task'];await app.shutdown();await runner.cleanup()
        print('PASS: actual Hermes plugin registration + PTB identity/reply/callback dispatch, SQLite dedup/pairing, restricted fallback, native buttons/doc delivery IDs, gateway application restart/outage recovery. Telegram network mocked; NOT a live handshake.')

if __name__=='__main__':asyncio.run(main())
