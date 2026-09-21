"""Local interactive setup. Never prints secrets and never polls Telegram independently."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
PROFILE = LOCAL / 'hermes-shipping'
PIN = json.loads((ROOT / 'hermes/hermes-pin.json').read_text())['commit']

def write_env(values):
    if any("'" in str(v) or '\n' in str(v) or '\r' in str(v) for v in values.values()):
        raise ValueError('Unsupported newline or quote in local configuration')
    text = ''.join(k + "='" + str(v) + "'\n" for k, v in values.items())
    (LOCAL / 'f2.env').write_text(text, encoding='utf-8')
    (PROFILE / '.env').write_text(text, encoding='utf-8')
    (LOCAL / 'f2-settings.json').write_text(json.dumps(values), encoding='utf-8')
    for path in [LOCAL/'f2.env', PROFILE/'.env', LOCAL/'f2-settings.json']:
        path.chmod(0o600)

def configure():
    LOCAL.mkdir(exist_ok=True)
    if (LOCAL/'f2-settings.json').exists():
        raise SystemExit('Configuration exists. Use approve or gateway; no credentials overwritten.')
    print('Paste the BotFather token at the hidden prompt. It stays in ignored .local files.')
    token = getpass.getpass('Telegram bot token (hidden): ').strip()
    if ':' not in token or len(token) < 25: raise SystemExit('Token format invalid; nothing saved.')
    target = PROFILE/'plugins/shipping-review'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT/'hermes/shipping-review', target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    (PROFILE/'config.yaml').write_text('platform_toolsets:\n  telegram: []\n  cli: []\nplugins:\n  enabled: [shipping-review]\nagent:\n  max_turns: 1\n', encoding='utf-8')
    write_env({'TELEGRAM_BOT_TOKEN':token,'TELEGRAM_ALLOWED_USERS':'0','F2_BRIDGE_TOKEN':secrets.token_hex(32),'F2_BACKEND_TOKEN':secrets.token_hex(32),'F2_BACKEND_URL':'http://127.0.0.1:5176','F2_DASHBOARD_URL':'http://localhost:5176','F2_RECIPIENTS':'[]','F2_ACTORS':'','SIMULATOR_STATE_FILE':str(LOCAL/'f2-simulator.json'),'F2_STATE_FILE':str(LOCAL/'f2-state.json'),'PORT':'5176','HERMES_HOME':str(PROFILE)})
    print('Saved private profile. Next: python scripts/f2_setup.py gateway\nThen send /start to your bot. No case data is sent before local approval.')

def approve():
    path=PROFILE/'shipping-inbound.sqlite'
    if not path.exists():raise SystemExit('Start the dedicated gateway and send /start first.')
    with closing(sqlite3.connect(path)) as db: rows=db.execute('SELECT actor,chat FROM pairing').fetchall()
    if not rows:raise SystemExit('No private /start observed. Send /start again while the gateway is running.')
    for i,(actor,chat) in enumerate(rows,1):print(f'{i}. Telegram user {actor}, private chat {chat}')
    selected=int(input('Select YOUR test account number (verify in Telegram): '))-1
    if not 0<=selected<len(rows):raise SystemExit('Invalid selection')
    actor,chat=rows[selected]
    if input(f'Authorize synthetic case messages and documents ONLY to user {actor}, chat {chat}? Type AUTHORIZE: ')!='AUTHORIZE':raise SystemExit('Not authorized; unchanged.')
    values=json.loads((LOCAL/'f2-settings.json').read_text())
    values.update(TELEGRAM_ALLOWED_USERS=actor,F2_ACTORS=actor,F2_RECIPIENTS=json.dumps([{'actor':actor,'chat':chat,'operator':True}]))
    write_env(values)
    print('Authorized selected test chat as business user and test operator. Restart gateway and F2 services, then send /start again.')

def gateway(runtime):
    repo=Path(runtime).resolve()
    revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    if revision!=PIN:raise SystemExit('Hermes commit differs from tested pin. Re-run compatibility tests before updating pin.')
    values=json.loads((LOCAL/'f2-settings.json').read_text())
    shutil.copytree(ROOT/'hermes/shipping-review', PROFILE/'plugins/shipping-review', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    env=os.environ.copy();env.update(values)
    if env.get('TELEGRAM_WEBHOOK_URL'):
        raise SystemExit('The verified shipping profile requires long polling; remove TELEGRAM_WEBHOOK_URL before startup.')
    env['PYTHONPATH']=os.pathsep.join([str(LOCAL/'f2-python'),str(repo)])
    # Only the dedicated Hermes gateway consumes updates. Never run a separate getUpdates script.
    interpreter=repo/('venv/Scripts/python.exe' if os.name=='nt' else 'venv/bin/python')
    subprocess.run([str(interpreter),'-m','hermes_cli.main','gateway','run'],env=env,cwd=ROOT,check=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['configure','approve','gateway'])
    parser.add_argument('--runtime',default=str(Path(os.environ.get('LOCALAPPDATA',''))/'hermes/hermes-agent'))
    args=parser.parse_args()
    if args.action=='configure':configure()
    elif args.action=='approve':approve()
    else:gateway(args.runtime)
