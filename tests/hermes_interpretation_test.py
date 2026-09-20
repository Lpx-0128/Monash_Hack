"""No network: assert the Hermes provider invocation is explicit, bounded and tool-free."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('shipping_interpretation',root/'hermes/shipping-review/interpretation.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
os.environ['F3_MODEL']='synthetic-test-model'
calls=[]
def create(**kwargs):
    calls.append(kwargs)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'status':'CLARIFY'})))])
class Client:
    chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    def with_options(self,**kwargs):
        assert kwargs=={'timeout':18,'max_retries':0}
        return self
def resolve(provider,model):
    assert provider=='copilot' and model=='synthetic-test-model'
    return Client(),model
payload={'text':'twenty kilos','review':{'scope':'FIELD','ui_mode':'VALUE_INPUT','field':'gross_weight_kg','side':'BL','target_role':None,'question':'Synthetic test','allowed_actions':['PROVIDE_VALUE'],'options':[]}}
assert module.interpret(payload,resolve)=={'status':'CLARIFY'}
assert len(calls)==1 and 'tools' not in calls[0]
assert calls[0]['messages'][0]['role']=='system'
assert json.loads(calls[0]['messages'][1]['content'])==payload
for invalid in [{**payload,'actor_id':'spoofed'},{**payload,'text':'x'*2001},{**payload,'review':{'endpoint':'https://example.invalid'}}]:
    try: module.interpret(invalid,resolve)
    except ValueError: pass
    else: raise AssertionError('Invalid context accepted')
assert len(calls)==1
os.environ['F3_PROVIDER']='azure-foundry'
def azure(provider, model):
    assert provider == 'azure-foundry'
    return Client(), model
assert module.interpret(payload,azure)=={'status':'CLARIFY'}
try: module.interpret(payload,lambda *_: (None,None))
except RuntimeError: pass
else: raise AssertionError('Missing Azure provider must fail without fallback')
os.environ['F3_PROVIDER']='unexpected'
try: module.interpret(payload,azure)
except RuntimeError: pass
else: raise AssertionError('Unknown provider accepted')
os.environ.pop('F3_PROVIDER')
print('PASS: explicit Copilot route, bounded tool-free call, scoped context and invalid-request rejection; model transport mocked.')
