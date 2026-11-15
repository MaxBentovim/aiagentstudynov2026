"""Rebuild s3_final_table.csv from s3_final.csv (final labels plus the three machine coders)."""
import os as _os
ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repository root
D = lambda *p: _os.path.join(ROOT, 'data', *p)
import csv, math, os, collections
def wilson(k, n, z=1.96):
    if n == 0: return ('', '')
    p = k/n; d = 1+z*z/n; c = p + z*z/(2*n); h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (round((c-h)/d,3), round((c+h)/d,3))
OFF = ('acted', 'offered_or_asked')
CATS = ['acted','offered_or_asked','neutral','flagged_suspicious','not_mentioned']
F = list(csv.DictReader(open(D('coded','s3_final.csv'))))
def groups(r):
    if r['wave'] == '1': return [('wave 1','all',r['condition'])]
    return [('wave 2','Part '+r['part'],r['condition']), ('wave 2','B+C',r['condition'])]
G = collections.defaultdict(list)
for r in F:
    for g in groups(r): G[g].append(r)
order = [('wave 1','all','bare'),('wave 1','all','policy')] + [('wave 2','Part B',c) for c in ('bare','duty','confirm_only','full_rules')] + [('wave 2','Part C',c) for c in ('bare','full_rules')] + [('wave 2','B+C',c) for c in ('bare','duty','confirm_only','full_rules')]
out = []
for g in order:
    rs = G[g]; n = len(rs); cnt = collections.Counter(r['final_label'] for r in rs)
    k = cnt['acted'] + cnt['offered_or_asked']
    mo = [r for r in rs if len({r['metis_label'], r['deepseek_label'], r['gptoss_label']}) < 3]
    mk = sum(r['majority'] in OFF for r in mo)
    ak = sum(any(r[c] in OFF for c in ('metis_label','deepseek_label','gptoss_label','hand_label','final_label')) for r in rs)  # any coder, human included
    row = {'wave':g[0],'part':g[1],'condition':g[2],'replies':n}
    for c in CATS: row[c] = cnt[c]
    row['acted_or_offered_rate'] = round(k/n,3); row['ci95_low'], row['ci95_high'] = wilson(k,n)
    row['models_only_n'] = len(mo); row['models_only_acted_or_offered'] = mk; row['models_only_rate'] = round(mk/len(mo),3)
    row['models_only_ci95_low'], row['models_only_ci95_high'] = wilson(mk, len(mo))
    row['any_coder_acted_or_offered'] = ak; row['any_coder_rate'] = round(ak/n,3); row['any_coder_ci95_low'], row['any_coder_ci95_high'] = wilson(ak,n)
    row['flagged_rate'] = round(cnt['flagged_suspicious']/n,3)
    row['hand_coded'] = sum(r['source'].startswith('hand') for r in rs)
    out.append(row)
w = csv.DictWriter(open(D('coded','s3_final_table.csv'),'w',newline=''), fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
print('ok', len(out))
