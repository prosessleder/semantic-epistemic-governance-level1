#!/usr/bin/env python3
"""Build the readable companion from canonical TeX; no experimental changes."""
from pathlib import Path
import re,subprocess

ROOT=Path(__file__).resolve().parents[1]


def convert(text,shift=True):
    argv=['pandoc','--from=latex','--to=gfm','--wrap=none']
    if shift:argv.append('--shift-heading-level-by=1')
    return subprocess.run(argv,input=text,text=True,capture_output=True,check=True).stdout


def sync():
    raw=(ROOT/'paper/paper.tex').read_text()
    title=re.search(r'\\title\{([^}]+)\}',raw).group(1)
    abstract=re.search(r'\\begin\{abstract\}(.*?)\\end\{abstract\}',raw,re.S).group(1).strip()
    body=raw.split('\\end{frontmatter}',1)[1].split('\\begin{thebibliography}',1)[0]
    bibliography=raw.split('\\begin{thebibliography}',1)[1].split('\\end{thebibliography}',1)[0]
    items=re.findall(r'\\bibitem\{([^}]+)\}(.*?)(?=\\bibitem|\Z)',bibliography,re.S)
    refs={key:str(i) for i,(key,_) in enumerate(items,1)}
    counts={'table':0,'figure':0};targets={}
    for match in re.finditer(r'\\begin\{(table|figure)\}(.*?)\\end\{\1\}',body,re.S):
        kind,block=match.groups();counts[kind]+=1
        label=re.search(r'\\label\{([^}]+)\}',block)
        if label:targets[label.group(1)]=str(counts[kind])
    before,after=body.split('\\appendix',1)
    for text,appendix in [(before,False),(after,True)]:
        n=0
        for match in re.finditer(r'\\section(\*)?\{[^}]+\}(?:\\label\{([^}]+)\})?',text):
            if match.group(1):continue
            n+=1
            if match.group(2):targets[match.group(2)]='Appendix '+chr(64+n) if appendix else str(n)
    body=re.sub(r'\\ref\{([^}]+)\}',lambda m:targets[m.group(1)],body)
    body=re.sub(r'\\citep?\{([^}]+)\}',lambda m:'['+', '.join(refs[k] for k in m.group(1).split(','))+']',body)
    def figure(match):
        block=match.group(0)
        if '\\begin{tikzpicture}' not in block:return block
        if '\\label{fig:ten-pass-intervals}' not in block:raise ValueError('Unmapped scientific figure')
        caption=re.search(r'\\caption\{(.*?)\}\\label',block,re.S).group(1)
        return '\\begin{figure}\\includegraphics{figures/ten-pass-intervals.png}\\caption{'+caption+'}\\end{figure}'
    body=re.sub(r'\\begin\{figure\}.*?\\end\{figure\}',figure,body,flags=re.S)
    body=re.sub(r'% BEGIN GENERATED[^\n]*|% END GENERATED[^\n]*','',body)
    text='# '+title+'\n\nTimothy O’Brien · [ORCID 0009-0001-2589-347X](https://orcid.org/0009-0001-2589-347X)\n\nPreprint 0.2.0, 19 October 2026. Not peer reviewed. Independent researcher; no institutional affiliation. Copyright 2026 Timothy O’Brien. [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).\n\n## Abstract\n\n'+convert(abstract,False)+'\n'+convert(body)
    text+='\n## References\n\n'+convert('\\begin{enumerate}\n'+'\n'.join('\\item '+content.strip() for _,content in items)+'\n\\end{enumerate}',False)
    text=re.sub(r'<span id="[^"]+"></span>','',text)
    text=re.sub(r'<div id="[^"]+">|</div>','',text)
    text=re.sub(r'\$`([^`]+)`\$',lambda m:'$'+m.group(1)+'$',text)
    text=re.sub(r'\n{3,}','\n\n',text)
    (ROOT/'paper/paper.md').write_text(text)
    print('Synchronized readable manuscript from canonical TeX')


if __name__=='__main__':sync()
