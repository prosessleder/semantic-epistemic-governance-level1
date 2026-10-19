#!/usr/bin/env python3
"""Publication figures from saved amended statistics; no rescoring or inference."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]
ALIASES=['gpt61sol','gpt56terra','qwen38','gpt6luna','sonnet55','haiku55']
LABELS=['Sol','Terra','Qwen','Luna','Sonnet','Haiku']


def build():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    source=ROOT/'results/ten-pass-amended-v1/results/analysis.json';a=json.loads(source.read_text())
    out=ROOT/'paper/figures';out.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(11,5.6),sharey=True,layout='constrained')
    for ax,t in zip(axes,['semantic','epistemic']):
        u=a['unit_sensitivity'][t+'--primary']
        for i,alias in enumerate(ALIASES):
            z=a['models'][alias][t]['primary']['ten_round_summary']
            lo,hi=u['case_weighted_intervals'][alias];ax.plot([lo,hi],[i,i],color='#A76F3E',linewidth=1.8,label='Unit-resampling sensitivity' if i==0 else None)
            lo,hi=z['fixed_corpus_generation_resampling_interval'];ax.plot([lo,hi],[i,i],color='#2166AC',linewidth=5,label='Generation interval (fixed test set)' if i==0 else None)
            ax.scatter([z['mean']],[i],color='#152E40',s=30,zorder=3)
        ax.set_title(t.capitalize()+' · strict scoring');ax.set_xlim(-.01,1.025);ax.xaxis.set_major_formatter(PercentFormatter(1));ax.grid(axis='x',alpha=.15);ax.set_xlabel('Amended ten-pass complete-answer mean')
    axes[0].set_yticks(range(6),LABELS);axes[0].invert_yaxis()
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=2,frameon=False)
    fig.suptitle('Basic Level 1: amended ten-run results, two conditional 95% intervals\nOriginal primary remains incomplete; ten later follow-ups are included',fontsize=11)
    fig.savefig(out/'ten-pass-intervals.png',dpi=220);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,5.5),sharey=True,layout='constrained')
    for ax,t in zip(axes,['semantic','epistemic']):
        for delta,mode,color,label in [(-.18,'primary','#2166AC','Strict bare JSON'),(.18,'framing_sensitivity','#D97706','Sole outer fence')]:
            values=[a['models'][alias][t][mode]['ten_round_summary']['mean'] for alias in ALIASES]
            ax.barh([i+delta for i in range(6)],values,height=.32,color=color,label=label)
        ax.set_title(t.capitalize());ax.set_xlim(0,1.025);ax.xaxis.set_major_formatter(PercentFormatter(1));ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True);ax.set_xlabel('Amended ten-pass mean complete-answer score')
    axes[0].set_yticks(range(6),LABELS);axes[0].invert_yaxis();axes[1].legend(loc='lower right',fontsize=8)
    fig.suptitle('Basic Level 1: answer-contract sensitivity, not a reasoning intervention\nMedium native reasoning · 32,768 combined tokens · same retained finals',fontsize=11)
    fig.savefig(out/'ten-pass-format-sensitivity.png',dpi=220);plt.close(fig)
    paths=[out/'ten-pass-intervals.png',out/'ten-pass-format-sensitivity.png']
    (out/'ten-pass-provenance.json').write_text(json.dumps(dict(scope='Display only; source statistics and saved finals unchanged',source=str(source.relative_to(ROOT)),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),figures={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')


if __name__=='__main__':build()
