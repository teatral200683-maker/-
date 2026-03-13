import json
with open('/opt/crypto-bot/config.json', 'r') as f:
    cfg = json.load(f)
cfg['trading']['trailing_tp_enabled'] = False
with open('/opt/crypto-bot/config.json', 'w') as f:
    json.dump(cfg, f, indent=4)
print('trailing_tp_enabled =', cfg['trading']['trailing_tp_enabled'])
