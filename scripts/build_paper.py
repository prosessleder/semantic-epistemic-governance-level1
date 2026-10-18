#!/usr/bin/env python3
"""Build manuscript views from saved results; never performs model inference.

Optional authoring dependencies: matplotlib, pandoc, Tectonic. Benchmark replay
itself remains standard-library-only. TeX retains its native vector plots.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ALIASES = ['gpt61sol', 'gpt56terra', 'qwen38', 'gpt6luna', 'sonnet55', 'haiku55']
LABELS = ['Sol', 'Terra', 'Qwen', 'Luna', 'Sonnet', 'Haiku']


def build_figures():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    reports = [json.loads((ROOT / f'results/main/{a}/original-report.json').read_text()) for a in ALIASES]
    out = ROOT / 'paper/figures'
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    note = 'Requested medium reasoning | 32,768 combined tokens | one judgment per DEV case'
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True, layout='constrained')
    for ax, track, denom in zip(axes, ['semantic', 'epistemic'], [48, 96]):
        x = list(range(6))
        for offset, mode, color, label in [(-.19, 'primary', '#2166ac', 'Strict JSON'), (.19, 'framing_sensitivity', '#d97706', 'Sole outer fence')]:
            vals = [100 * r['tracks'][track][mode]['full_correct'] / denom for r in reports]
            bars = ax.bar([i+offset for i in x], vals, .36, label=label, color=color)
            ax.bar_label(bars, labels=[str(r['tracks'][track][mode]['full_correct']) for r in reports], fontsize=8, padding=2)
        ax.set(xticks=x, xticklabels=LABELS, title=f'{track.capitalize()} ({denom} cases)', ylim=(0, 112))
        ax.grid(axis='y', alpha=.2); ax.set_axisbelow(True)
    axes[0].set_ylabel('Complete answers (%)'); axes[1].legend(loc='upper right', fontsize=8)
    fig.suptitle('Level 1 complete-answer accuracy\n'+note, fontsize=11)
    save(fig, out / 'complete-answer-accuracy', plt)

    colors = ['#2166ac', '#b2182b', '#1b7837', '#762a83', '#e08214', '#4d4d4d']
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True, layout='constrained')
    for ax, track in zip(axes, ['semantic', 'epistemic']):
        for r, label, color in zip(reports, LABELS, colors):
            vals = []
            for tier in (1, 2, 3):
                records = [v for v in r['records'] if v['split']=='dev' and v['track']==track and v['tier']==tier]
                correct = sum(bool(v['framing_sensitivity']['score'].get('all_correct', v['framing_sensitivity']['score'].get('correct',False))) for v in records)
                vals.append(100 * correct / len(records))
            ax.plot([1,2,3], vals, 'o-', color=color, label=label, linewidth=1.5)
        ax.set(title=track.capitalize(), xticks=[1,2,3], xlabel='Construction tier', ylim=(-3,105))
        ax.grid(alpha=.2)
    axes[0].set_ylabel('Complete answers, sole-fence parsing (%)'); axes[1].legend(fontsize=8)
    fig.suptitle('Performance by tier (tiers are not a calibrated difficulty scale)\n'+note, fontsize=11)
    save(fig, out / 'development-tiers', plt)

    fields=['supported_facts_correct','repair_correct','decisions_correct','possibilities_correct','query_optimal']
    fig, ax = plt.subplots(figsize=(9,4.8), layout='constrained')
    for r, label, color in zip(reports, LABELS, colors):
        vals = [100*r['tracks']['epistemic']['framing_sensitivity']['fields_correct'][f]/96 for f in fields]
        ax.plot(range(5), vals, 'o-', color=color, label=label, linewidth=1.5)
    ax.set(xticks=range(5), xticklabels=['Supported facts','Valid repair','All decisions','Possible outcomes','Next check'], ylim=(-3,105), ylabel='Whole packets correct, sole-fence parsing (%)')
    ax.grid(alpha=.2); ax.legend(fontsize=8, loc='lower right')
    fig.suptitle('Epistemic answer components (96 DEV packets)\n'+note, fontsize=11)
    save(fig, out / 'epistemic-components', plt)
    inputs = {str((ROOT/f'results/main/{a}/original-report.json').relative_to(ROOT)): hashlib.sha256((ROOT/f'results/main/{a}/original-report.json').read_bytes()).hexdigest() for a in ALIASES}
    (out/'provenance.json').write_text(json.dumps({'scope':'Figures from preserved Level 1 reports, no new inference or rescoring.', 'inputs':inputs,'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.png'))}},indent=2)+'\n')


def save(fig, stem, plt):
    fig.savefig(stem.with_suffix('.png'), dpi=220)
    plt.close(fig)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--pdf', action='store_true')
    parser.add_argument('--figures', action='store_true')
    args=parser.parse_args()
    if args.figures:
        build_figures()
    out=ROOT/'output/pdf'; out.mkdir(parents=True,exist_ok=True)
    source=out/'semantic-epistemic-governance-level1.tex'
    shutil.copyfile(ROOT/'paper/paper.tex',source)
    subprocess.run(['pandoc',str(ROOT/'paper/paper.md'),'--standalone','--embed-resources','--resource-path='+str(ROOT/'paper'),'--mathml','--metadata=pagetitle:Level 1 Semantic and Epistemic Governance','--output='+str(ROOT/'output/paper.html')],check=True)
    if args.pdf:
        subprocess.run(['tectonic','--only-cached','--keep-logs','--keep-intermediates','--outdir',str(out),str(source)],check=True)
    print('Built manuscript views; saved benchmark artifacts unchanged.')
