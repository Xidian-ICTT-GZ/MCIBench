"""Instantiate every catalog SQL public schema in real MySQL; no answer claims."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.lab import mysql_runtime,problem_io


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    index=json.loads((ROOT/'local/lab/data/problem_index.json').read_text(encoding='utf8'))
    qids=[row['qid'] for row in index if problem_io.kind(row['qid'])=='database']
    report={'scope':'all_catalog_database_public_schema_instantiation_only','runtime':mysql_runtime.identity(),
            'notice':'Actual DDL and public input insertion only. SELECT 1 is a transport fixture, not a solution or a functional correctness gate. Unspecified type widths/precision remain inferred.',
            'checks':[]}
    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    with mysql_runtime.Session(0) as session:
        for qid in qids:
            session.qid=qid
            session.runtime_ms=0  # Each problem retains its own query budget.
            cases,_,_=problem_io.official(qid)
            for case_index,case in enumerate(cases):
                try:
                    problem_io.check_database_input(qid,case['args'],cases[0]['args'])
                    output=session.run_case('SELECT 1 AS schema_ready',case['args'],{'mode':'table'},len(report['checks']))
                    if output!={'columns':['schema_ready'],'rows':[[1]]}:raise ValueError('schema transport fixture failed')
                    check={'qid':qid,'case_index':case_index,'schema':session.schemas[-1]['tables'],'passed':True}
                except (ValueError,mysql_runtime.SQLFailure) as error:
                    check={'qid':qid,'case_index':case_index,'passed':False,'error':str(error)[:1000]}
                report['checks'].append(check)
                save()
            print(qid,len(cases),'PUBLIC SCHEMA',all(c['passed'] for c in report['checks'] if c['qid']==qid),flush=True)
        report['verified_container_isolation']=session.environment['verified_isolation']
    report['problem_count']=len(qids);report['public_input_count']=len(report['checks']);save()
    failures=[c for c in report['checks'] if not c['passed']]
    print('Native MySQL public schemas:',len(qids),'problems;',len(report['checks']),'inputs; failures:',len(failures))
    raise SystemExit(bool(failures))


if __name__=='__main__':main()
