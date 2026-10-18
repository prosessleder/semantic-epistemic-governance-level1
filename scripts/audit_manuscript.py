#!/usr/bin/env python3
"""Check manuscript tables and plotted coordinates against preserved reports.

This is an artifact audit, not new inference, a new empirical score writer,
or independent scientific validation of the task specification.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re

ROOT=Path(__file__).resolve().parents[1]
md=(ROOT/'paper/paper.md').read_text(); tex=(ROOT/'paper/paper.tex').read_text()
checks=0
def check(condition, detail):
    global checks
    checks+=1
    assert condition, detail
def read(path): return json.loads((ROOT/path).read_text())
def sha(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
names={'GPT-6.1-Sol':'gpt61sol','GPT-5.6-Terra':'gpt56terra','Qwen3.8-27B':'qwen38','GPT-6-Luna':'gpt6luna','Sonnet-5.5':'sonnet55','Haiku-5.5':'haiku55','Opus-5.5':'opus55','Gemini-3.8-Flash':'gemini38','Gemma-4-31B':'gemma31','GLM-5.3-Flash':'glm','Nemotron-3.5-Super-VL':'nemotron35'}
reports={a:read(f'results/main/{a}/original-report.json') for a in list(names.values())[:6]}
tables=[];current=[]
for line in md.splitlines()+['']:
    if line.startswith('|'):current.append([c.strip() for c in line.strip('|').split('|')])
    elif current:tables.append(current[2:]);current=[]
check(len(tables)==11,'table count')
def rate(cell,n,d):
    check(cell==f'{n}/{d} ({100*n/d:.1f}%)',(cell,n,d))
for row in tables[3]:
    r=reports[names[row[0]]];check(row[1]=='medium','effort')
    for cell,(track,mode) in zip(row[2:],[(t,m) for t in ['semantic','epistemic'] for m in ['primary','framing_sensitivity']]):
        x=r['tracks'][track][mode];rate(cell,x['full_correct'],x['cases'])
for row in tables[4]:
    name,track,mode=row[0].split(', ');r=reports[names[name]];mode='primary' if mode=='strict' else 'framing_sensitivity'
    for tier,cell in enumerate(row[1:],1):
        records=[v for v in r['records'] if v['split']=='dev' and v['track']==track and v['tier']==tier]
        n=sum(bool(v[mode]['score'].get('all_correct',v[mode]['score'].get('correct',False))) for v in records)
        rate(cell,n,len(records))
for table,track,mode,fields in [(5,'semantic','primary',['goal_correct','expansion_permissions','expansion_witnesses','approval_matches','release_allowed']),(6,'epistemic','framing_sensitivity',['supported_facts_correct','repair_correct','decisions_correct','possibilities_correct','query_optimal'])]:
    for row in tables[table]:
        x=reports[names[row[0]]]['tracks'][track][mode]
        for cell,field in zip(row[1:],fields):rate(cell,x['fields_correct'].get(field,0),x['cases'])
for row in tables[7]:
    x=reports[names[row[0]]]['paired_epistemic'];p=x['presentation'];c=x['controlled_contrasts']
    for cell,n,d in zip(row[1:],[p['identical_decisions'],p['both_correct_decisions'],c['authority']['both_correct_on_changed'],c['provenance']['both_correct_on_changed']],[48,48,3,13]):rate(cell,n,d)
for row in tables[8]:
    name,mode=row[0].split(', ');x=reports[names[name]]['tracks']['epistemic']['primary' if mode=='strict' else 'framing_sensitivity']
    for cell,n,d in zip(row[1:],[x['decision_correct'],x['allow_on_deny'],x['allow_on_unknown'],x['justified_allow']],[224,112,90,22]):rate(cell,n,d)
for row in tables[9]:
    x=reports[names[row[0]]]['tracks']
    vals=[x[t][m]['parse_errors'] for t in ['semantic','epistemic'] for m in ['primary','framing_sensitivity']]
    vals += [sum(x[t]['primary'][key] for t in ['semantic','epistemic']) for key in ['token_limits','provider_error_finishes']]
    check([int(v) for v in row[1:]]==vals,('delivery',row[0]))
for row in tables[10]:
    a=names[row[0]];x=read(f'results/historical-three-check/{a}/expected-stages.json')
    for cell,key in zip(row[2:5],['first','check3_evidence','check3_reflection']):
        n=x[key]['all_five_correct'];check(cell==f'{n} ({100*n/480:.1f}%)',('historical',a,key))
    check(int(row[5])==x['first']['false_approvals'],('historical false approvals',a))
    d=read(f'results/historical-three-check/{a}/dataset.json')
    check(len(d['scenarios'])==480 and sum(not s['truth']['release_allowed'] for s in d['scenarios'])==288,('historical denominators',a))

sem=read('data/original-prepared/semantic-cases.json');epi=read('data/original-prepared/epistemic-cases.json')['cases']
check(len(sem['train'])==len(sem['dev'])==48,'semantic split')
check(Counter(v['split'] for v in epi)=={'train':48,'dev':96},'epistemic split')
check(sum(len(v['input']['actions']) for v in epi)==336,'constructed action denominator')
check(sum(len(v['input']['actions']) for v in epi if v['split']=='dev')==224,'DEV action denominator')
check(len({v['unit_id'] for v in epi if v['split']=='dev'})==12,'DEV units')

# Verify every data coordinate in the three native TeX figures, in figure order.
coordinates=re.findall(r'coordinates\s*\{([^;]+)\};',tex)
check(len(coordinates)==22,'native plot series count')
actual=[[tuple(map(float,p)) for p in re.findall(r'\(([-\d.]+),([-\d.]+)\)',s)] for s in coordinates]
expected=[];ordered=list(reports.values())
for track in ['semantic','epistemic']:
    for mode in ['primary','framing_sensitivity']:
        expected.append([(100*r['tracks'][track][mode]['full_correct']/r['tracks'][track][mode]['cases'],i+1) for i,r in enumerate(ordered)])
for track in ['semantic','epistemic']:
    for r in ordered:
        points=[]
        for tier in [1,2,3]:
            records=[v for v in r['records'] if v['split']=='dev' and v['track']==track and v['tier']==tier]
            n=sum(bool(v['framing_sensitivity']['score'].get('all_correct',v['framing_sensitivity']['score'].get('correct',False))) for v in records)
            points.append((tier,100*n/len(records)))
        expected.append(points)
for r in ordered:
    fields=r['tracks']['epistemic']['framing_sensitivity']['fields_correct']
    expected.append([(i+1,100*fields[k]/96) for i,k in enumerate(['supported_facts_correct','repair_correct','decisions_correct','possibilities_correct','query_optimal'])])
for a,e in zip(actual,expected):
    check(len(a)==len(e),'plot point count')
    for (x,y),(u,v) in zip(a,e):check(abs(x-u)<1e-6 and abs(y-v)<1e-6,('plot coordinate',x,y,u,v))

for filename in ['paper/paper.md','paper/paper.tex']:
    text=(ROOT/filename).read_text()
    check('/Users/' not in text, 'local path leakage')
    check('github.com/prosessleder/semantic-epistemic-governance-level2' not in text,'unfinished work link')
    check('120/120' not in text,'unpackaged diagnostic')
    check('This research received no external funding.' in text,'funding')
check(not re.search(r'\b(?:tab|sec):[\w-]+',md),'raw cross-reference in Markdown')
for rel in re.findall(r'!\[[^]]*\]\(([^)]+)\)',md):check((ROOT/'paper'/rel).is_file(),('figure path',rel))
citations=set(k for group in re.findall(r'\\citep?\{([^}]+)\}',tex) for k in group.split(','))
bib=set(re.findall(r'\\bibitem\{([^}]+)\}',tex))
check(citations==bib and len(bib)==21,'cited bibliography')
out={'status':'PASS','checks':checks,'scope':'Current manuscript tables/coordinates and saved-report denominators. Offline replay performed separately. No model calls; no peer-review claim.','manuscripts':{p:sha(p) for p in ['paper/paper.md','paper/paper.tex']},'reports':{f'results/main/{a}/original-report.json':sha(f'results/main/{a}/original-report.json') for a in reports},'table_count':11,'plot_series':22,'bibliography_entries':len(bib)}
print(json.dumps(out,indent=2))
