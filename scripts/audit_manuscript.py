#!/usr/bin/env python3
"""Audit current manuscript cells against saved evidence, without inference.

Generated manuscript metadata is compared to independent record counts, never
used as scientific ground truth. Complete statistical/scorer replay is a separate
offline command. This checks its saved intervals and independently counts moments,
components, execution histories and case consistency. No credentials or network.
"""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import math
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT/'results/ten-pass-amended-v1'
MODELS = ['gpt61sol', 'gpt56terra', 'qwen38', 'gpt6luna', 'sonnet55', 'haiku55']
SHORT = dict(zip(MODELS, ['Sol', 'Terra', 'Qwen', 'Luna', 'Sonnet', 'Haiku']))
TRACKS = ['semantic', 'epistemic']
PARSERS = ['primary', 'framing_sensitivity']
REPORTING = 'framing_sensitivity'  # v0.2.1: ignore a sole presentation fence
PINNED_REFERENCES = {
    'kaos': 'https://ontology.ihmc.us/Papers/uszok_kaos_policy08.pdf',
    'margrave': 'https://cs.brown.edu/people/kfisler/Pubs/icse05.pdf',
    'logicaldiff': 'https://arxiv.org/abs/1401.5850v1',
    'survey': 'https://arxiv.org/abs/1804.07805v1',
    'ontologytools': 'https://arxiv.org/abs/2602.03439v1',
    'pcas': 'https://arxiv.org/abs/2602.16708v1',
    'linc': 'https://aclanthology.org/2023.emnlp-main.313/',
    'critic': 'https://arxiv.org/abs/2305.11738v4',
    'mtbench': 'https://arxiv.org/abs/2306.05685v4',
    'authorizationclosure': 'https://arxiv.org/abs/2609.32428v1',
    'governeddeduction': 'https://arxiv.org/abs/2609.31029v1',
    'committime': 'https://arxiv.org/abs/2609.31490v1',
    'pentad': 'https://pentad.ai/PLRN/029/',
    'sufficientcontext': 'https://arxiv.org/abs/2411.06037v3',
    'abstentionbench': 'https://arxiv.org/abs/2506.09038v1',
    'memoryconflict': 'https://arxiv.org/abs/2605.30087v1',
    'camel': 'https://arxiv.org/abs/2503.18813v2',
    'memlineage': 'https://arxiv.org/abs/2605.14421v1',
    'repairkb': 'https://arxiv.org/abs/2003.05746v5',
    'graphecho': 'https://arxiv.org/abs/2609.17695v1',
    'epistemiccues': 'https://arxiv.org/abs/2610.12788v1',
}
checks = 0

def check(condition, detail):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(detail)

def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def correct(record, parser):
    s = record[parser]['score']
    return bool(s.get('all_correct', s.get('correct', False)))
def percent(value): return f'{100*value:.3f}'
def interval(values): return '--'.join(percent(x) for x in values)
def normalize(value):
    value = re.sub(r'\\(?:texttt|textbf|emph)\{([^{}]*)\}', r'\1', str(value))
    value = value.replace('\\%', '%').replace('\\_', '_').replace('`', '')
    value = re.sub(r'\\+(?=[*_])', '', value)
    return re.sub(r'\s+', ' ', value.replace('–', '--').replace('—', '---')).strip()
def normalized_rows(rows): return [[normalize(x) for x in row] for row in rows]
def outcome(r, mode):
    if r.get('refusal') or r.get('finish_reason') == 'content_filter': return 'native_filter_or_refusal'
    if r.get('provider_error') or r.get('finish_reason') == 'error': return 'native_provider_error'
    if r.get('finish_reason') == 'length': return 'native_length'
    v = r[mode]
    if v.get('parse_error'): return 'unparseable_final'
    s = v['score']
    if s.get('valid_format', s.get('valid_schema', True)) is False or ('reason' in s and not s.get('fields')): return 'schema_invalid'
    return 'correct' if correct(r, mode) else 'completed_task_error'

def tex_tables(tex):
    result, ordered = {}, []
    for block in re.findall(r'\\begin\{table\}.*?\\end\{table\}', tex, re.S):
        label = re.search(r'\\label\{([^}]+)\}', block)
        check(label is not None, 'Table without stable label')
        label = label.group(1)
        check(label not in result, 'Duplicate table '+label)
        content = block.split('\\toprule', 1)[1].split('\\end{tabular}', 1)[0]
        content = re.sub(r'\\(?:toprule|midrule|bottomrule)', '', content)
        rows = [[normalize(c) for c in row.split('&')] for row in re.split(r'\\\\', content) if row.strip()]
        check(len(rows) > 1, 'Empty table '+label)
        result[label] = dict(headers=rows[0], rows=rows[1:], block=block)
        ordered.append(label)
    return result, ordered

def markdown_tables(md):
    tables, current = [], []
    for line in md.splitlines()+['']:
        if line.startswith('|'): current.append([normalize(c) for c in line.strip('|').split('|')])
        elif current:
            check(len(current) > 2, 'Empty Markdown table')
            tables.append(dict(headers=current[0], rows=current[2:])); current = []
    return tables

def expected_tables(records, primary, analysis, original_analysis):
    expected = {}
    def add(label, headers, rows):
        check(label not in expected, 'Duplicate expected table '+label)
        expected[label] = dict(headers=headers, rows=rows)
    rows = []
    for alias in MODELS:
        plan = read(ROOT/f'results/main/{alias}/execution-plan.json')
        config, settings = plan['config'], plan['settings']
        check(settings['max_tokens'] == 32768 and settings['reasoning']['effort'] == 'medium', 'Frozen inference settings '+alias)
        check(settings['provider']['allow_fallbacks'] is False, 'Provider fallback '+alias)
        check(('temperature' in settings and settings['temperature'] == 0) if alias == 'qwen38' else 'temperature' not in settings, 'Temperature setting '+alias)
        provider = config['provider'] + (' FP8' if config['tag'].endswith('/fp8') and config['provider'] == 'Chutes' else '')
        rows.append([SHORT[alias], config['model'], provider])
    add('tab:configurations', ['Short name', 'Model identifier', 'Pinned provider'], rows)
    old_attempts = read(PACKAGE/'primary/data/attempt-ledger.json')['attempts']
    new_attempts = read(PACKAGE/'followup/attempt-ledger.json')['attempts']
    rows = []
    for leg, title in [('original','Original'), ('async','Queue continuation'), ('recovery','Never-submitted recovery'), ('fourth','Final never-submitted leg'), ('followup','Unknown-outcome follow-up')]:
        xs = new_attempts if leg == 'followup' else [a for a in old_attempts if a['leg'] == leg]
        nums = [sum(a['status'] == k for a in xs) for k in ['complete','unknown-outcome','http-error']]
        rows.append([title]+[f'{n:,}' for n in nums+[len(xs)]])
    add('tab:execution', ['Execution','Received finals','New unknowns','Transient failures','Closed attempts'], rows)
    summary, intervals, original, categories = [], [], [], []
    for alias in MODELS:
        for track in TRACKS:
            xs = [r for r in records if r['alias'] == alias and r['track'] == track]
            denom = 48 if track == 'semantic' else 96
            check(len(xs) == denom*10, 'Incomplete amended track')
            rates = [sum(correct(r,REPORTING) for r in xs if r['round'] == n)/denom for n in range(1,11)]
            q = analysis['models'][alias][track][REPORTING]['ten_round_summary']
            mean, sd = statistics.mean(rates), statistics.stdev(rates)
            check(math.isclose(mean,q['mean'],abs_tol=1e-15) and math.isclose(sd,q['round_sample_sd'],abs_tol=1e-15), 'Saved moments differ')
            check(q['round_range'] == [min(rates),max(rates)], 'Saved pass range differs')
            summary.append([SHORT[alias],track[0].upper(),f"{sum(correct(r,REPORTING) for r in xs)}/{denom*10}",percent(mean),percent(sd),interval([min(rates),max(rates)])])
            units = defaultdict(list)
            for r in xs: units[r['unit_id']].append(int(correct(r,REPORTING)))
            check(len(units) == 12, 'Underlying unit inventory')
            equal_unit = statistics.mean(statistics.mean(v) for v in units.values())
            unit = analysis['unit_sensitivity'][track+'--'+REPORTING]
            check(math.isclose(equal_unit,unit['unit_weighted_means'][alias],abs_tol=1e-15), 'Equal-unit mean differs')
            check(q['generation_draws'] == 20000 and q['generation_seed'] == 2026101803, 'Generation seed/draws')
            check(unit['draws'] == 20000 and unit['seed'] == 2026101804, 'Unit seed/draws')
            intervals.append([SHORT[alias],track[0].upper(),interval(q['fixed_corpus_generation_resampling_interval']),interval(unit['case_weighted_intervals'][alias]),percent(equal_unit)])
            prior = [r for r in primary if r['alias'] == alias and r['track'] == track]
            oq = original_analysis['models'][alias][track][REPORTING]['ten_round_summary']
            prior_mean = percent(sum(correct(r,'primary') for r in prior)/(denom*10)) if oq is not None else 'Unavailable'
            original.append([SHORT[alias],track[0].upper(),f'{len(prior)}/{denom*10}',denom*10-len(prior),prior_mean])
            check((oq is None) == (len(prior) != denom*10), 'Original null estimate altered')
            for mode in PARSERS:
                counts = Counter(outcome(r,mode) for r in xs)
                check(dict(counts) == analysis['models'][alias][track][mode]['exclusive_outcomes'], 'Saved categories differ')
                check(not set(counts)-{'correct','completed_task_error','unparseable_final','schema_invalid'}, 'Native-error finish contradicts table')
                categories.append([SHORT[alias],track[0].upper(),'strict' if mode == 'primary' else 'fence']+[counts[k] for k in ['correct','completed_task_error','unparseable_final','schema_invalid']])
    add('tab:ten-pass-summary', ['Config.','Track','Correct','Mean','SD','Pass range'], summary)
    add('tab:ten-pass-intervals', ['Config.','Track','Generation interval','Unit sensitivity','Equal-unit mean'], intervals)
    add('tab:native-outcomes', ['Config.','Track','Parser','Correct','Error','Parse','Schema'], categories)
    add('tab:original-primary', ['Config.','Track','Received/planned','Unknown','Full-ten mean'], original)
    check(sum(row[-1] == 'Unavailable' for row in original) == 5, 'Five original null means')
    for track in TRACKS:
        denom = 48 if track == 'semantic' else 96
        for mode in PARSERS:
            rows = [[str(n)]+[percent(sum(correct(r,mode) for r in records if r['alias'] == alias and r['track'] == track and r['round'] == n)/denom) for alias in MODELS] for n in range(1,11)]
            add('tab:rounds-'+track+'-'+mode, ['Pass']+[SHORT[a] for a in MODELS], rows)
        rows = []
        for alias in MODELS:
            indexed = defaultdict(list)
            for r in records:
                if r['alias'] == alias and r['track'] == track: indexed[r['original_id']].append(correct(r,REPORTING))
            check(len(indexed) == denom and all(len(x) == 10 for x in indexed.values()), 'Ten generations per case')
            histogram = Counter(sum(x) for x in indexed.values())
            rows.append([SHORT[alias]]+[histogram[n] for n in range(11)])
        add('tab:consistency-'+track, ['Config.']+[str(n) for n in range(11)], rows)
        fields = (['goal_correct','expansion_permissions','expansion_witnesses','approval_matches','permission_authorized','release_allowed'] if track == 'semantic' else ['supported_facts_correct','repair_correct','decisions_correct','possibilities_correct','query_optimal'])
        headers = ['Config.']+(['Goals','Gains','Witness','Approval','Auth.','Release'] if track == 'semantic' else ['Facts','Repair','Decisions','Possible','Query'])
        for mode in PARSERS:
            rows = []
            for alias in MODELS:
                xs = [r for r in records if r['alias'] == alias and r['track'] == track]
                ns = [sum(bool((r[mode]['score'].get('fields',{}) if track == 'semantic' else r[mode]['score']).get(k)) for r in xs) for k in fields]
                rows.append([SHORT[alias]]+ns)
            add('tab:components-'+track+'-'+mode, headers, rows)
    rows = []
    for alias in MODELS:
        saved = read(ROOT/f'results/main/{alias}/original-report.json')
        values = []
        for track in TRACKS:
            xs = [r for r in saved['records'] if r['split'] == 'dev' and r['track'] == track]
            denom = 48 if track == 'semantic' else 96
            check(len(xs) == denom, 'Historical single-pass coverage')
            values += [f'{sum(correct(r,mode) for r in xs)}/{denom}' for mode in PARSERS]
        rows.append([SHORT[alias]]+values)
    add('tab:historical-single', ['Config.','Semantic strict','Semantic fence','Epistemic strict','Epistemic fence'], rows)
    sem = read(ROOT/'data/original-prepared/semantic-cases.json')
    epi = read(ROOT/'data/original-prepared/epistemic-cases.json')['cases']
    check(len(sem['train']) == len(sem['dev']) == 48, 'Full semantic split')
    check(Counter(c['split'] for c in epi) == {'train':48,'dev':96}, 'Full epistemic split')
    check(sum(1 << len(c['contract']['public_classes']) for c in sem['train']+sem['dev']) == 172032, 'Profile comparison count')
    check(Counter(Counter(c['group_id'] for c in sem['dev']).values()) == {6:6,2:6}, 'Twelve semantic groups')
    check(Counter(Counter(c['unit_id'] for c in epi if c['split'] == 'dev').values()) == {8:12}, 'Twelve epistemic units')
    check(sum(len(c['input']['actions']) for c in epi if c['split'] == 'dev') == 224, 'DEV actions')
    columns = []
    for n in [1,2,3]:
        ss = [c for c in sem['train']+sem['dev'] if c['tier'] == 'tier-'+str(n)]
        es = [c for c in epi if c['tier'] == n]
        def one(values):
            check(len(set(values)) == 1, 'Tier property not constant'); return str(values[0])
        def bounds(values): return f'{min(values)}--{max(values)}'
        columns.append([one([len(c['contract']['base']['classes']) for c in ss]),one([len(c['contract']['public_classes']) for c in ss]),f"{1 << len(ss[0]['contract']['public_classes']):,}",bounds([len(c['proposal']) for c in ss]),one([len(c['contract']['protected_permissions']) for c in ss]),one([len(c['input']['atoms']) for c in es]),bounds([len(c['input']['reports']) for c in es]),one([len(c['input']['actions']) for c in es])])
    props = ['Semantic classes','Public seed classes','Profiles checked per version','Edits per batch','Protected permissions','Epistemic Boolean atoms','Reports per packet','Separate release decisions']
    add('tab:challenge-tiers', ['Property','Tier 1','Tier 2','Tier 3'], [[name]+[col[i] for col in columns] for i,name in enumerate(props)])
    decisions = [[True and (not expansion or False),False and (not expansion or False)] for expansion in [False,True]]
    add('tab:epistemic-grey-example', ['Evidence interpretation','Task A','Task B'], [['Keep the claim that permission does not expand']+['Allow' if x else 'Deny' for x in decisions[0]],['Keep the claim that permission expands']+['Allow' if x else 'Deny' for x in decisions[1]],['Conclusion justified across both','Undetermined','Deny']])
    historical = [('opus55','Opus-5.5'),('gpt61sol','GPT-6.1-Sol'),('gemini38','Gemini-3.8-Flash'),('haiku55','Haiku-5.5'),('gemma31','Gemma-4-31B'),('gpt56terra','GPT-5.6-Terra'),('qwen38','Qwen3.8-27B'),('gpt6luna','GPT-6-Luna'),('glm','GLM-5.3-Flash'),('nemotron35','Nemotron-3.5-Super-VL'),('sonnet55','Sonnet-5.5')]
    rows = []
    for alias, name in historical:
        base = ROOT/f'results/historical-three-check/{alias}'
        result, dataset, plan = read(base/'expected-stages.json'),read(base/'dataset.json'),read(base/'execution-plan.json')
        check(len(dataset['scenarios']) == 480 and sum(not c['truth']['release_allowed'] for c in dataset['scenarios']) == 288, 'Historical correction denominators')
        check(plan['settings']['max_tokens'] == 8192, 'Historical correction cap')
        ns = [result[k]['all_five_correct'] for k in ['first','check3_evidence','check3_reflection']]
        rows.append([name,plan['settings']['reasoning'].get('effort','enabled*')]+[f'{n} ({100*n/480:.1f}%)' for n in ns]+[result['first']['false_approvals']])
    add('tab:l1-historical-feedback', ['Model','Reasoning','First C (/480)','Evidence C, check 3','Reflection C, check 3','First F (/288)'], rows)
    return expected

def audit(refresh_metadata=False):
    tex, md = (ROOT/'paper/paper.tex').read_text(),(ROOT/'paper/paper.md').read_text()
    generated = read(ROOT/'paper/ten-pass-generated.json')
    spec = importlib.util.spec_from_file_location('publication_capsule_reader',PACKAGE/'replay.py')
    reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)
    verified = reader.verify(PACKAGE,False)
    check(verified['amended_received'] == 8640 and verified['original_primary_received'] == 8630 and verified['original_primary_unknown'] == 10 and verified['original_study_complete'] is False,'Original/amended distinction')
    primary = read(PACKAGE/'primary/data/final-projections.json')['records']
    fresh = read(PACKAGE/'followup/final-projections.json')['records']
    records = primary+[dict(r,slot_id=r['original_slot_id']) for r in fresh]
    analysis, original = read(PACKAGE/'results/analysis.json'),read(PACKAGE/'primary/results/analysis.json')
    expected = expected_tables(records,primary,analysis,original)
    actual, order = tex_tables(tex)
    check(set(actual) == set(expected) and len(actual) == 20,'All twenty manuscript tables')
    cells = 0
    for label, table in expected.items():
        check(actual[label]['headers'] == normalized_rows([table['headers']])[0],'TeX header '+label)
        rows = normalized_rows(table['rows'])
        check(len(actual[label]['rows']) == len(rows),'TeX row count '+label)
        for n,(got,want) in enumerate(zip(actual[label]['rows'],rows)):
            check(len(got) == len(want),'TeX column count '+label)
            for i,(left,right) in enumerate(zip(got,want)):
                check(left == right,f'Independent TeX cell {label} row{n} col{i}: {left!r} != {right!r}'); cells += 1
        if label in generated['tables']:
            g = generated['tables'][label]
            check(normalized_rows([g['headers']])[0] == actual[label]['headers'],'Generated header '+label)
            check(normalized_rows(g['rows']) == rows,'Generated table differs from evidence '+label)
    check(set(generated['tables']) == set(expected)-{'tab:challenge-tiers','tab:epistemic-grey-example','tab:l1-historical-feedback'},'Seventeen generated tables')
    check(generated['analysis_sha256'] == sha(PACKAGE/'results/analysis.json') and generated['original_analysis_sha256'] == sha(PACKAGE/'primary/results/analysis.json'),'Generated analysis bindings')
    blocks = dict(re.findall(r'% BEGIN GENERATED ([^\n]+)\n(.*?)% END GENERATED \1',tex,re.S))
    check(set(blocks) == set(generated['blocks']) and len(blocks) == 18,'Eighteen generated blocks')
    drift = []
    for label, block in blocks.items():
        if block != generated['blocks'][label]:
            check(re.sub(r'\s+','',block) == re.sub(r'\s+','',generated['blocks'][label]),'Generated block differs beyond typography '+label)
            drift.append(label)
    coords = re.findall(r'coordinates\s*\{([^;]+)\};',blocks['fig:ten-pass-intervals'])
    wanted = []
    for track in TRACKS:
        for y,alias in enumerate(MODELS,1):
            q = analysis['models'][alias][track][REPORTING]['ten_round_summary']
            for xs in [analysis['unit_sensitivity'][track+'--'+REPORTING]['case_weighted_intervals'][alias],q['fixed_corpus_generation_resampling_interval'],[q['mean']]]:
                wanted.append([(100*x,y) for x in xs])
    check(len(coords) == len(wanted) == 36,'Plot series count')
    points = 0
    for series,target in zip(coords,wanted):
        parsed = [tuple(map(float,p)) for p in re.findall(r'\(([-\d.]+),([-\d.]+)\)',series)]
        check(len(parsed) == len(target),'Plot point count')
        for got,want in zip(parsed,target):
            check(abs(got[0]-want[0]) < 1e-7 and got[1] == want[1],'Plot coordinate differs'); points += 1
    md_tables = markdown_tables(md)
    check(len(md_tables) == len(order),'Markdown table count')
    for table,label in zip(md_tables,order):
        check(table['headers'] == actual[label]['headers'],'Markdown header '+label)
        check(table['rows'] == actual[label]['rows'],'Markdown values '+label)
    citations = set(k for group in re.findall(r'\\cite[pt]?\{([^}]+)\}',tex) for k in group.split(','))
    bibliography = dict(re.findall(r'\\bibitem\{([^}]+)\}(.*?)(?=\\bibitem|\\end\{thebibliography\})',tex,re.S))
    check(citations == set(bibliography) == set(PINNED_REFERENCES) and len(bibliography) == 21,'Twenty-one cited references')
    for key,url in PINNED_REFERENCES.items(): check(re.findall(r'\\url\{([^}]+)\}',bibliography[key]) == [url],'Reference pin '+key)
    body = tex.split('\\clearpage\\appendix',1)[0]
    for phrase in [r'one fresh judgment per case',r'current study uses one judgment',r'150 saved observations per model',r'900 across the six',r'fewer than half of the epistemic',r'seven Qwen and nine Terra',r'Qwen achieves 45/48',r'Sol achieves 48/48 and 95/96',r'Qwen solves 45/48',r'one-shot study']:
        check(re.search(phrase,body,re.I) is None,'Stale single-pass claim '+phrase)
    for text in [tex,md]:
        check('/Users/' not in text and '/private/tmp/' not in text,'Private manuscript path')
        check('This research received no external funding.' in text,'Funding statement')
        check('The author declares no competing interests.' in text,'Directly author-confirmed competing-interest declaration')
        check('8,630' in text and '8,640' in text and 'post-hoc' in text,'Original/amended disclosure')
        check('2026101803' in text and '2026101804' in text and '20,000' in text,'Distinct seed/draw disclosure')
    check(not re.search(r'\b(?:tab|sec|fig|app):[\w-]+',md),'Raw unresolved Markdown label')
    for rel in re.findall(r'!\[[^]]*\]\(([^)]+)\)',md): check((ROOT/'paper'/rel).is_file(),'Missing Markdown figure '+rel)
    for alias,n in [('qwen38',375),('gemma31',371)]:
        h = read(ROOT/f'results/source-evidence-supporting/ontology-{alias}-epistemic-sources-results-2026-10-15.json')['model']['test']
        check(h['cases'] == 384 and h['decision_correct'] == 380 and h['all_eight_correct'] == n,'Historical source-evidence counts')
    if refresh_metadata:
        check(bool(drift),'No typography-only metadata drift to refresh')
        for label in drift:
            generated['blocks'][label] = blocks[label]
            if label in generated['tables']:
                cap = re.search(r'\\caption\{(.*?)\}\\label\{',blocks[label],re.S)
                check(cap is not None,'Missing refreshed caption'); generated['tables'][label]['caption'] = cap.group(1)
        (ROOT/'paper/ten-pass-generated.json').write_text(json.dumps(generated,indent=2)+'\n')
    else: check(not drift,'Typography-only derivative metadata drift; use --refresh-generated-metadata after independent checks')
    return dict(status='PASS_CURRENT_TEN_PASS_MANUSCRIPT_EVIDENCE_AUDIT',checks=checks,displayed_table_cells=cells,tables=20,generated_tables=17,generated_blocks=18,plot_series=36,plotted_points=points,bibliography_entries=21,
        original_primary_received=8630,original_primary_unknown=10,original_study_complete=False,amended_received=8640,complete_amended_model_tracks=12,
        manuscript_sha256={n:sha(ROOT/n) for n in ['paper/paper.tex','paper/paper.md','paper/ten-pass-generated.json']},
        evidence_sha256={n:sha(PACKAGE/n) for n in ['results/analysis.json','primary/results/analysis.json','manifest.json']},
        independent_derivation='Displayed cells from saved projections/plans/results; moments/components/consistency independently counted; interval endpoints from frozen analysis with full replay performed separately',
        typography_metadata_refreshed=drift if refresh_metadata else [],pending_author_action=None,author_declarations_confirmed=True,scope='Numeric/source synchronization and declared scope; no external peer-review or compiled-page QA claim',new_model_calls=0,frozen_sources_changed=False)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-generated-metadata',action='store_true',help='Sync typography-only derivative blocks after independent evidence checks')
    args = parser.parse_args()
    print(json.dumps(audit(args.refresh_generated_metadata),sort_keys=True,indent=2))
