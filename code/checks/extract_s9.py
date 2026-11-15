import json, re, csv, collections
import os as _os
ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repository root
D = lambda *p: _os.path.join(ROOT, 'data', *p)
def parse(t):
    if not t: return None
    t=t.strip()
    m=re.search(r'\{.*\}', t, re.S)
    if not m: return None
    s=m.group(0)
    try: return json.loads(s)
    except Exception:
        # try trimming to last brace progressively
        for end in range(len(s),0,-1):
            if s[end-1]=='}':
                try: return json.loads(s[:end])
                except Exception: pass
    return None
rows=[]
for fn,wave in [('calls.jsonl','1'),('calls_wave2.jsonl','2')]:
    for line in open(D('raw',fn)):
        r=json.loads(line)
        sc=r.get('scenario','')
        if not sc.startswith('S9'): continue
        ph=r.get('phase','')
        if 'pilot' in ph: continue
        j=parse(r.get('response_text'))
        um=r['user_message']; m=re.search(r'Message from Jordan: "(.*)"',um,re.S)
        base=dict(wave=wave,phase=ph,part=r.get('part','W1'),scenario=sc,wording=r.get('wording','W1'),condition=r['condition'],model=r['model'].split('/')[-1],run_id=r['run_id'],user_msg=m.group(1) if m else um[-200:])
        if j is None:
            rows.append({**base,'parsed':'no','n_disputes':0,'reason':'','statement':'','message_to_user':'','other_tools':''}); continue
        calls=j.get('tool_calls') or []
        ds=[c for c in calls if isinstance(c,dict) and c.get('tool')=='file_dispute']
        other=';'.join(c.get('tool','?') for c in calls if isinstance(c,dict) and c.get('tool')!='file_dispute')
        if not ds:
            rows.append({**base,'parsed':'yes','n_disputes':0,'reason':'','statement':'','message_to_user':j.get('message_to_user',''),'other_tools':other})
        for d in ds:
            a=d.get('arguments') or {}
            rows.append({**base,'parsed':'yes','n_disputes':len(ds),'reason':a.get('reason',''),'statement':a.get('statement',''),'message_to_user':j.get('message_to_user',''),'other_tools':other})
w=csv.DictWriter(open(D('checks','s9_statements.csv'),'w',newline=''),fieldnames=list(rows[0].keys()))
w.writeheader(); w.writerows(rows)
c=collections.Counter((r['wave'],r['part'],r['wording'],r['condition'],r['n_disputes']>0) for r in rows)
for k,v in sorted(c.items()): print(k,v)
print(len(rows), sum(1 for r in rows if r['statement']))
print(collections.Counter((r['part'],r['wording'],r['user_msg']) for r in rows))
