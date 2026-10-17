#!/usr/bin/env python3
"""Offline benchmark verification/replay. No network or credential interface."""
from pathlib import Path
from collections import defaultdict
import argparse,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from internal.benchmarks import ontology_semantic_challenge_v2 as sem1
from internal.benchmarks import ontology_epistemic_challenge_v2 as epi1

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def parse(raw,fence=False):
    if fence and isinstance(raw,str):
        m=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',raw.strip(),re.S)
        if m:raw=m[1]
    def pairs(xs):
        result={}
        for k,v in xs:
            if k in result:raise ValueError('duplicate key')
            result[k]=v
        return result
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite'))),None
    except (ValueError,TypeError):return None,'invalid final JSON'

def verify():
    m=read(ROOT/'release-manifest.json')
    for item in m['files']:
        p=ROOT/item['path'];assert sha(p)==item['sha256'] and p.stat().st_size==item['bytes'],item['path']
    if m['level']==1:
        s=read(ROOT/'data/original-prepared/semantic-cases.json');e=read(ROOT/'data/original-prepared/epistemic-cases.json')
        assert len(s['train'])+len(s['dev'])==96 and len(e['cases'])==144
        assert len(read(ROOT/'data/evaluated-cases.json')['cases'])==150
    else:
        cases=read(ROOT/'data/evaluation-cases.json')['cases'];assert len(cases)==72
        assert len({c['unit_id'] for c in cases if c['track']=='semantic'})==24
        assert sum(c['track']=='epistemic' for c in cases)==24
    return dict(status='PASS',level=m['level'],files=len(m['files']),network_calls=0,manifest_sha256=sha(ROOT/'release-manifest.json'))

def replay_level1():
    rows=read(ROOT/'data/evaluated-cases.json')['cases'];lookup={c['id']:c for c in rows};models={}
    for path in sorted((ROOT/'results/main').glob('*/predictions.jsonl')):
        report=read(path.parent/'original-report.json');expected={r['id']:r for r in report['records']};counts=defaultdict(lambda:dict(cases=0,correct=0))
        predictions=[json.loads(line) for line in path.read_text().splitlines()];assert len(predictions)==150
        for prediction in predictions:
            c=lookup[prediction['id']];old=expected[c['id']]
            for fence,name in [(False,'primary'),(True,'framing_sensitivity')]:
                answer,error=parse(prediction['final_text'],fence)
                score={} if error else epi1.score(c['case']['input'],answer) if c['track']=='epistemic' else sem1.score_answer(c['case'],answer)
                assert answer==old[name]['answer'] and score==old[name]['score'],(path.parent.name,c['id'],name)
                if c['split']=='dev':
                    g=counts[c['track']+'-'+name];g['cases']+=1;g['correct']+=bool(score.get('all_correct',score.get('correct',False)))
        for track in ['semantic','epistemic']:
            for mode in ['primary','framing_sensitivity']:
                expected_count=report['tracks'][track][mode];g=counts[track+'-'+mode]
                assert g==dict(cases=expected_count['cases'],correct=expected_count['full_correct'])
        models[path.parent.name]=dict(counts)
    assert len(models)==6
    historical={}
    for directory in sorted((ROOT/'results/historical-three-check').iterdir()):
        data=read(directory/'dataset.json');lookup={s['scenario_id']:s for s in data['scenarios']}
        histories=read(directory/'trajectories.json');expected=read(directory/'expected-stages.json');assert len(histories)==480
        totals={}
        for stage,arm,outkey in [(1,'checker-evidence','first'),(3,'checker-evidence','check3_evidence'),(3,'reflection-only','check3_reflection')]:
            correct=0
            for sid,arms in histories.items():
                history=arms[arm];assert 1<=len(history)<=3
                assert all(r['verdict']!=lookup[sid]['truth'] for r in history[:-1])
                row=history[min(stage,len(history))-1];correct+=row['verdict']==lookup[sid]['truth']
            assert correct==expected[outkey]['all_five_correct'];totals[outkey]=correct
        historical[directory.name]=totals
    assert len(historical)==11
    return dict(status='PASS',main=models,historical=historical,scope='Offline score replay, not fresh inference or independent regeneration of model outputs.')

def replay_level2():
    from internal.benchmarks import ontology_semantic_global_v5 as sem2
    from internal.benchmarks import ontology_epistemic_packing_v5 as epi2
    allcases=read(ROOT/'data/development-cases.json')['cases'];lookup={c['id']:c for c in allcases};groups={}
    for path in sorted((ROOT/'results/development').glob('*.json')):
        report=read(path);counts=defaultdict(lambda:dict(cases=0,correct=0))
        for row in report['records']:
            c=lookup[row['id']];score=(sem2 if c['track']=='semantic' else epi2).score(c,row['answer'])
            # Native length/schema failures are retained by the frozen scorer.
            assert score==row['score'],(path.name,row['id'])
            g=counts[str(row.get('width'))+'-'+row['phase']];g['cases']+=1;g['correct']+=score['all_correct']
        groups[path.stem]=dict(counts)
    return dict(status='PASS',development=groups,fresh_evaluation='Running separately; no fabricated score',network_calls=0)

def score_file(path):
    level=read(ROOT/'release-manifest.json')['level'];data=read(ROOT/('data/evaluated-cases.json' if level==1 else 'data/evaluation-cases.json'))['cases'];lookup={c['id']:c for c in data};outputs=[]
    if level==2:
        from internal.benchmarks import ontology_semantic_global_v5 as sem2
        from internal.benchmarks import ontology_epistemic_packing_v5 as epi2
    seen=set()
    for line in path.read_text().splitlines():
        value=json.loads(line);assert value['id'] not in seen;seen.add(value['id']);c=lookup[value['id']];answer,error=parse(value['final_text'])
        if level==1:score={} if error else epi1.score(c['case']['input'],answer) if c['track']=='epistemic' else sem1.score_answer(c['case'],answer)
        else:score=(sem2 if c['track']=='semantic' else epi2).score(c,answer)
        outputs.append(dict(id=c['id'],score=score,parse_error=error))
    return dict(status='SCORED',submitted=len(outputs),planned=len(data),complete_input_coverage=seen==set(lookup),records=outputs)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['verify','replay','score']);p.add_argument('--responses',type=Path);a=p.parse_args()
    check=verify()
    result=check if a.command=='verify' else score_file(a.responses) if a.command=='score' else replay_level1() if check['level']==1 else replay_level2()
    print(json.dumps(result,sort_keys=True))
