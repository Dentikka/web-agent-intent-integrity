import random
from point2_v3.design import task,user_task,POLICIES
COMMON=('Use only the supplied tools on this isolated local application. No real payment occurs. '
 'Preceding verification-assistant tool calls, if present, count toward the action budget. Supplied quotes were obtained after reloading the current document. Preparation acknowledgments indicate observations withheld by the assigned evidence-delivery condition; they are not site quotes. '
 'Preserve all user constraints. Do not repeat an uncertain final submission. ')

def matrix(models):
    cells=[]
    for model in models:
        for app in ('ea','medusa'):
            for i in range(12):
                for condition in ('aligned_under','aligned_over','ui_stale_under','ui_stale_over','tool_stale_under','tool_stale_over'):
                    for arm in ('fresh_ui','fresh_tool','full'):
                        c=task(app,i%6,condition,policy='evidence',model_id=model)
                        c['task_id']=i
                        c.update(block='active_source',evidence_arm=arm,study='review_active_source')
                        if app=='medusa':
                            handle,title=[('t-shirt','Medusa T-Shirt'),('shorts','Medusa Shorts'),('sweatshirt','Medusa Sweatshirt')][i//4]
                            c.update(handle=handle,product=title,size=['S','M','L','XL'][i%4],color='White' if i%2==0 else 'Black')
                            reprice(c)
                        else:
                            service,duration=[('Deep Tissue Massage',60),('Haircut',45),('Express Massage',30)][i//4]
                            low=[35,50,65,80][i%4];under=condition.endswith('under')
                            c.update(service=service,duration=duration,actual_total=low if under else low+20,
                                old_price=low+20 if under else low,cap=low+10,day=f'2026-10-{26+i%5:02d}')
                        cells.append(c)
        for i in range(12):
            for effort in (1,7):
                for budget in ('normal','double'):
                    for condition in ('tool_stale_under','tool_stale_over'):
                        c=task('medusa',i%6,condition,model_id=model)
                        handle,title=[('t-shirt','Medusa T-Shirt'),('shorts','Medusa Shorts'),('sweatshirt','Medusa Sweatshirt')][i//4]
                        c.update(task_id=100+i,handle=handle,product=title,size=['S','M','L','XL'][i%4],color='White' if i%2==0 else 'Black')
                        reprice(c)
                        c.update(block='effort_budget',study='review_effort',evidence_arm='none',ui_steps=effort,budget=budget,
                            turn_budget=28 if budget=='normal' else 56,action_budget=48 if budget=='normal' else 96)
                        cells.append(c)
        for i in range(6):
            for feasible in (False,True):
                for arm in ('baseline','fresh_ui','fresh_tool','full'):
                    c=task('ea',i,'tool_stale_under' if feasible else 'tool_stale_over',model_id=model,
                        policy='baseline' if arm=='baseline' else 'evidence')
                    c.update(block='duration',study='review_duration',evidence_arm=arm,feasible=feasible,
                        actual_total=50,old_price=50,cap=60,actual_duration=c['duration']+(0 if feasible else 15),
                        old_duration=c['duration']+(15 if feasible else 0))
                    cells.append(c)
    random.Random(2026102407).shuffle(cells)
    assert len(cells)==576*len(models)
    return cells

def reprice(c):
    unit={'S':12,'M':16,'L':22,'XL':26}[c['size']];actual=unit+(10 if c['shipping']=='Standard Shipping' else 20)
    c.update(unit_price=unit,actual_total=actual,cap=(actual+5 if c['condition'].endswith('under') else actual-5) if c['stale_side']=='none' else unit+15)
