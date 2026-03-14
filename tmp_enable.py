import json
import urllib.request

token = "8375020207:AAFjYpamZkD3s9XfAZ334aQJ4jqpKPL251I"

commands = [
    {"command": "status", "description": "Tekushiy status bota"},
    {"command": "pnl", "description": "PnL za den/nedelyu/mesyac"},
    {"command": "config", "description": "Tekushiye nastroyki"},
    {"command": "stop", "description": "Ostanovit bota"},
    {"command": "help", "description": "Spisok komand"},
]

url = f"https://api.telegram.org/bot{token}/setMyCommands"
data = json.dumps({"commands": commands}).encode()
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read())
print("OK" if result.get("ok") else result)
