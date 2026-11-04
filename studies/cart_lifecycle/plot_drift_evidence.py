"""Publication-exportable plot with model episodes and scripted controls separated."""
import argparse
import collections
import csv
import json
from pathlib import Path


def run(root: Path,out: Path,controls: Path | None=None) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    out.mkdir(parents=True,exist_ok=True)
    counts=collections.Counter();errors=0
    for file in (root/'paid/main').glob('*/result.json'):
        result=json.loads(file.read_text(encoding='utf8'))
        if result['error']:
            errors+=1;continue
        backend=json.loads((file.parent/'backend.json').read_text(encoding='utf8'))
        state=backend['final']
        agrees=all(state['form'][k]==state['saved']['items'][0][k] for k in ('product_id','quantity'))
        counts[(agrees,result['scores']['task_success'])]+=1
    control=json.loads((controls or root/'resync-controls/controls.json').read_text(encoding='utf8'))
    assert control['complete']
    matrix=[];n=[];data=[]
    for entry in ('ui','tool'):
        line=[];den=[]
        for action in ('save','refresh'):
            rows=[r for r in control['rows'] if r['entry']==entry and r['synchronization']==action]
            assert rows and all(r['agree_before_commit'] for r in rows)
            correct=sum(r['score']['task_success'] for r in rows)
            line.append(correct/len(rows));den.append((correct,len(rows)))
            data.append(dict(panel='scripted_controls',condition=f'{entry}:{action}',correct=correct,total=len(rows)))
        matrix.append(line);n.append(den)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'svg.fonttype':'none','pdf.fonttype':42})
    fig,axs=plt.subplots(1,2,figsize=(10.8,4.8),gridspec_kw={'width_ratios':[1,1.25]})
    ax=axs[0];values=[counts[(True,True)],counts[(False,True)]]
    bars=ax.bar(['Form = saved cart','Form ≠ saved cart'],values,color=['#854C65','#9DE1FC'],width=.58)
    ax.set_ylabel('Correct model episodes');ax.set_ylim(0,max(1,max(values))*1.22)
    ax.set_title('(a) Correct orders can leave a stale form',loc='left',fontsize=11)
    for bar,v in zip(bars,values):ax.text(bar.get_x()+bar.get_width()/2,v+1,str(v),ha='center',fontsize=12)
    ax.text(.5,-.38,f'{sum(values)} correct orders / {sum(counts.values())} valid model episodes\n{errors} technical stops excluded',ha='center',transform=ax.transAxes,fontsize=9)
    for side in ('top','right'):ax.spines[side].set_visible(False)
    ax=axs[1];ax.imshow(matrix,vmin=0,vmax=1,cmap=ListedColormap(['#854C65','#9DE1FC']),aspect='auto')
    ax.set_xticks([0,1],['Save form\nform → saved cart','Reload cart\nsaved cart → form'])
    ax.set_yticks([0,1],['Last edit in UI','Last edit via tool'])
    ax.set_title('(b) Agreement can preserve the wrong selection',loc='left',fontsize=11)
    for i in range(2):
        for j in range(2):
            yes,total=n[i][j]
            ax.text(j,i,f'{yes}/{total} correct\n'+('intent preserved' if yes else 'intent lost'),
                ha='center',va='center',color='#242126' if yes else 'white',fontsize=11)
    ax.text(.5,-.38,'All 8 scripted controls agree before checkout.\nApplication paths, not model error rates.',ha='center',transform=ax.transAxes,fontsize=9)
    for side in ax.spines.values():side.set_visible(False)
    fig.subplots_adjust(left=.075,right=.98,bottom=.36,top=.84,wspace=.47)
    for ext in ('png','pdf','svg'):fig.savefig(out/f'intent-and-agreement.{ext}',dpi=200)
    plt.close(fig)
    data += [dict(panel='model_episodes',condition=str(eq),correct=counts[(eq,True)],total=sum(v for (a,s),v in counts.items() if a==eq)) for eq in (True,False)]
    with (out/'figure-data.csv').open('w',encoding='utf8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['panel','condition','correct','total']);writer.writeheader();writer.writerows(data)


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--controls',type=Path,help='Explicit shared resync-controls/controls.json')
    a=p.parse_args();run(a.root,a.out,a.controls)
