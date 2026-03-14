import json
with open('/opt/crypto-bot/config.json', 'r') as f:
    cfg = json.load(f)
if 'risk' not in cfg:
    cfg['risk'] = {}
cfg['risk']['anti_liquidation_pct'] = 30.0
with open('/opt/crypto-bot/config.json', 'w') as f:
    json.dump(cfg, f, indent=4)
print('anti_liquidation_pct =', cfg['risk']['anti_liquidation_pct'])
