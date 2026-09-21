"""One-shot Azure deallocation at the agreed deadline, using this VM's identity."""
import datetime
import json
import urllib.request

DEADLINE = datetime.datetime(2026, 9, 30, 16, tzinfo=datetime.timezone.utc)
if datetime.datetime.now(datetime.timezone.utc) < DEADLINE:
    raise SystemExit('Deadline has not arrived; no action taken')
metadata = 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fmanagement.azure.com%2F'
with urllib.request.urlopen(urllib.request.Request(metadata, headers={'Metadata': 'true'}), timeout=15) as response:
    token = json.load(response)['access_token']
resource = '/subscriptions/52597804-7254-4ee7-99ea-43c49033b2a4/resourceGroups/harbor-review-rg/providers/Microsoft.Compute/virtualMachines/harbor-review-vm'
request = urllib.request.Request('https://management.azure.com' + resource + '/deallocate?api-version=2024-07-01', data=b'', headers={'Authorization': 'Bearer ' + token}, method='POST')
with urllib.request.urlopen(request, timeout=30) as response:
    print('Azure deallocation accepted:', response.status)
