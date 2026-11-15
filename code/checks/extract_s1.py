import json,re,csv
import os as _os
ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repository root
D = lambda *p: _os.path.join(ROOT, 'data', *p)
def parse(t):
    m=re.search(r'\{.*\}', t or '', re.S)
    if not m: return None
    s=m.group(0)
    for end in range(len(s),0,-1):
        if s[end-1]=='}':
            try: return json.loads(s[:end])
            except Exception: pass
    return None
rows=[]
for fn,wave in [('calls.jsonl','1'),('calls_wave2.jsonl','2')]:
    for line in open(D('raw',fn)):
        r=json.loads(line)
        if not r.get('scenario','').startswith('S1') or r.get('scenario','').startswith('S10'): continue
        if 'pilot' in r.get('phase',''): continue
        j=parse(r.get('response_text'))
        msg=j.get('message_to_user','') if j else ''
        tools=';'.join(c.get('tool','?') for c in (j.get('tool_calls') or [])) if j else ''
        rows.append(dict(wave=wave,part=r.get('part','W1'),wording=r.get('wording','W1'),condition=r['condition'],model=r['model'].split('/')[-1],run_id=r['run_id'],parsed='yes' if j else 'no',tools=tools,msg=msg,raw=(r.get('response_text') or '')[:3000],reasoning_len=len(r.get('reasoning_text') or '')))
w=csv.DictWriter(open(D('checks','s1_all.csv'),'w',newline=''),fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
import collections
print(collections.Counter((r['wave'],r['part'],r['model']) for r in rows))
q=[r for r in rows if r['model'].startswith('qwen')]
print(len(q))
