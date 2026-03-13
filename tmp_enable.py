import json
with open('/opt/crypto-bot/config.json', 'r') as f:
    cfg = json.load(f)
cfg['trading']['trailing_tp_enabled'] = True
cfg['trading']['trend_filter_enabled'] = True
cfg['trading']['adaptive_sizing_enabled'] = True
with open('/opt/crypto-bot/config.json', 'w') as f:
    json.dump(cfg, f, indent=4)
print('OK')
for k in ['trailing_tp_enabled', 'trend_filter_enabled', 'adaptive_sizing_enabled']:
    print(f'  {k} = {cfg["trading"][k]}')
