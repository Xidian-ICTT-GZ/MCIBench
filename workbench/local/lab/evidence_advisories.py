"""Read-only, corpus-bound notices; never rewrite stored historical verdicts."""
import json
from pathlib import Path
import re
from local.lab.behavior import sha

DATA_FILE=Path(__file__).with_name('data')/'evidence_advisories.json'


def for_job(job):
    try:
        registry=json.loads(DATA_FILE.read_text(encoding='utf8'))
        if registry.get('version')!=1:return []
    except (OSError,ValueError,TypeError):return []
    output=[];result=job.get('result') or {}
    for issue in registry.get('issues',[]):
        if (type(issue) is not dict or type(issue.get('qid')) is not int or
                not re.fullmatch('[0-9a-f]{64}',str(issue.get('cases_sha256','')))):continue
        for snapshot in result.get('inputs',[]):
            if snapshot.get('qid')==issue['qid'] and snapshot.get('full_corpus') and sha(snapshot['full_corpus'])==issue['cases_sha256']:
                if issue.get('executor_sha256'):
                    if not any(g.get('qid')==issue['qid'] and (not issue.get('language') or g.get('language')==issue['language'])
                        and any(c.get('code_sha256')==issue.get('code_sha256')
                            and c.get('full_execution_evidence',{}).get('execution_environment',{}).get('executor_sha256')==issue['executor_sha256']
                            for c in g.get('candidates',[])) for g in result.get('groups',[])):continue
                output.append({**issue,'status':'invalidated_execution' if issue.get('executor_sha256') else 'invalidated_corpus','provenance':'derived_from_current_review_registry',
                               'stored_result_unchanged':True})
                break
    return output
