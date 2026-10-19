#!/usr/bin/env python3
"""Build current ten-round manuscript views; saved experimental data are read-only."""
from pathlib import Path
import argparse,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--pdf',action='store_true');p.add_argument('--figures',action='store_true');a=p.parse_args()
 if a.figures:subprocess.run([sys.executable,'-B',str(ROOT/'scripts/build_ten_pass_figures.py')],check=True)
 subprocess.run([sys.executable,'-B',str(ROOT/'scripts/sync_manuscript.py')],check=True)
 out=ROOT/'output/pdf';out.mkdir(parents=True,exist_ok=True)
 source=out/'semantic-epistemic-governance-level1.tex';shutil.copyfile(ROOT/'paper/paper.tex',source)
 subprocess.run(['pandoc',str(ROOT/'paper/paper.md'),'--standalone','--embed-resources','--resource-path='+str(ROOT/'paper'),'--mathml','--metadata=pagetitle:'+(ROOT/'paper/paper.md').read_text().splitlines()[0].removeprefix('# '),'--output='+str(ROOT/'output/paper.html')],check=True)
 if a.pdf:subprocess.run(['tectonic','--only-cached','--keep-logs','--keep-intermediates','--outdir',str(out),str(source)],check=True)
 print('Built current manuscript; scientific data unchanged')
if __name__=='__main__':main()
