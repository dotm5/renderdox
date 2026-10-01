"""Deterministic marker/pagination/large-integer UI fixture (not GPU timings)."""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workflows.reports import profile_report


def create(path):
    payload={'identity':{'scope':'Synthetic report UI fixture'},'counters':[{'counterId':1,'name':'Duration','unit':'Seconds'},
        {'counterId':2,'name':'Large integer','unit':'Count'}],'events':[]}
    for i in range(350):
        ancestry=[{'eventId':1,'name':'Root'},{'eventId':2 if i<175 else 3,'name':'Same marker name'}]
        payload['events'].append({'eventId':100+i,'action':{'name':'Draw <escaped>','ancestry':ancestry},'durationMs':1,
            'counters':[{'counterId':1,'value':.001,'valid':True},{'counterId':2,'value':2**64-2 if i==0 else None,'valid':i==0}]})
    payload['events'].append({'eventId':1,'action':{'name':'Root','ancestry':[]},'aggregateAction':True,'durationMs':350,
        'counters':[{'counterId':1,'value':.350,'valid':True}]})
    Path(path).write_text(profile_report(payload,'Report UI fixture'),encoding='utf-8')


if __name__=='__main__':create(sys.argv[1])
