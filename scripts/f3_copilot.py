"""Use the pinned Hermes Copilot login in the dedicated ignored profile."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['login', 'models', 'enable', 'disable'])
    p.add_argument('--model')
    p.add_argument('--worker', action='store_true')
    p.add_argument('--runtime', default=str(Path(os.environ.get('LOCALAPPDATA', ''))/'hermes/hermes-agent'))
    args = p.parse_args()
    runtime = Path(args.runtime).resolve()
    settings = ROOT/'.local/f2-settings.json'
    if args.action in ('enable','disable'):
        from f2_setup import write_env
        values=json.loads(settings.read_text())
        if args.action=='enable' and not args.model: raise SystemExit('Choose a model from the models command with --model')
        values['F3_ENABLED']='true' if args.action=='enable' else 'false'
        if args.model: values['F3_MODEL']=args.model
        write_env(values)
        print('Interpretation settings saved. Restart the dedicated gateway and interaction service.')
        return
    if not args.worker:
        pin=json.loads((ROOT/'hermes/hermes-pin.json').read_text())['commit']
        if subprocess.check_output(['git','-C',str(runtime),'rev-parse','HEAD'],text=True).strip()!=pin:
            raise SystemExit('Hermes pin differs; verify compatibility first')
        env=os.environ.copy();env.update(json.loads(settings.read_text()))
        env['PYTHONPATH']=os.pathsep.join([str(ROOT/'.local/f2-python'),str(runtime)])
        interpreter=runtime/('venv/Scripts/python.exe' if os.name=='nt' else 'venv/bin/python')
        raise SystemExit(subprocess.call([str(interpreter),str(Path(__file__).resolve()),args.action,'--worker'],env=env,cwd=ROOT))
    if args.action=='login':
        from hermes_cli.copilot_auth import copilot_device_code_login
        token=copilot_device_code_login()
        if not token: raise SystemExit('Login not completed; settings unchanged')
        sys.path.insert(0,str(ROOT/'scripts'))
        from f2_setup import write_env
        values=json.loads(settings.read_text())
        values['COPILOT_GITHUB_TOKEN']=token
        write_env(values)
        print('Copilot login saved in ignored dedicated profile; token not displayed.')
    else:
        from hermes_cli.models import _copilot_catalog
        models=_copilot_catalog('copilot',True)
        if not models: raise SystemExit('No Copilot models available; check subscription/login')
        print(json.dumps(models))

if __name__=='__main__': main()
