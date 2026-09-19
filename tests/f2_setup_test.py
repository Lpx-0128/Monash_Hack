"""No secrets/network: exercise the interactive setup with explicitly synthetic inputs."""
import importlib.util
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import subprocess

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('setup',root/'scripts/f2_setup.py')
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
with tempfile.TemporaryDirectory(prefix='harbor-setup-') as tmp:
    setup.LOCAL=Path(tmp);setup.PROFILE=Path(tmp)/'hermes-shipping'
    with patch.object(setup.getpass,'getpass',return_value='999:synthetic-token-not-a-real-credential'):
        setup.configure()
    settings=json.loads((setup.LOCAL/'f2-settings.json').read_text())
    assert settings['F2_RECIPIENTS']=='[]'
    assert settings['TELEGRAM_ALLOWED_USERS']=='0'
    with closing(sqlite3.connect(setup.PROFILE/'shipping-inbound.sqlite')) as db:
        db.execute('CREATE TABLE pairing(actor TEXT,chat TEXT)');db.execute("INSERT INTO pairing VALUES ('101','101')");db.commit()
    with patch('builtins.input',side_effect=['1','AUTHORIZE']):setup.approve()
    values=json.loads((setup.LOCAL/'f2-settings.json').read_text())
    assert json.loads(values['F2_RECIPIENTS'])==[{'actor':'101','chat':'101','operator':True}]
    # Test actual Node env-file parsing (nested JSON must not acquire literal escapes).
    subprocess.run(['node','--env-file='+str(setup.LOCAL/'f2.env'),'-e',"const a=JSON.parse(process.env.F2_RECIPIENTS);if(a[0].actor!=='101')process.exit(1)"],check=True)
    try:setup.configure()
    except SystemExit:pass
    else:raise AssertionError('Must not overwrite configured credentials')
print('PASS: hidden-prompt configuration, explicit local recipient approval, Node env parsing, no overwrite. All input credentials/IDs synthetic.')
