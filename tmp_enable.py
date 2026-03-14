import json
with open('/opt/crypto-bot/config.json', 'r') as f:
    cfg = json.load(f)
if 'risk' not in cfg:
    cfg['risk'] = {}
cfg['risk']['max_daily_loss_pct'] = 3.0
with open('/opt/crypto-bot/config.json', 'w') as f:
    json.dump(cfg, f, indent=4)
print('max_daily_loss_pct =', cfg['risk']['max_daily_loss_pct'])
