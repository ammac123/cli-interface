import json, sys
src, dst = sys.argv[1], sys.argv[2]
last = None
for line in open(src):
    try: o = json.loads(line)
    except Exception: continue
    m = o.get('message') or {}
    content = m.get('content') if isinstance(m, dict) else None
    for c in content if isinstance(content, list) else []:
        if isinstance(c, dict) and c.get('type') == 'tool_use' and 'andback' in c.get('name', ''):
            last = max((v for v in c.get('input', {}).values() if isinstance(v, str)), key=len)
open(dst, 'w').write(last or '')
print(dst, len(last or ''))
