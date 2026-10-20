"""Audit/repair/verify reviewed lab problems; never import or overwrite formal results."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from local.common import REPO_ROOT, KEY_TO_LABEL, load_reference
from local.harness import runner
from local.harness.identity import image_digest
from local.lab.behavior import sha
from local.lab import input_contracts as contracts
from local.lab import correctness_audit as audit
from local.lab import audited_judging
from local.lab.correctness_assets import fixtures
from local.lab.catalog import load_cases
from local.lab.testcase_workflow import read_bundle, save, lock, DATA_DIR as CORPUS_DIR


def repair(qid, row, image, cache_dir, *, check_cancel=lambda:None):
    """Publish reviewed witness inputs only after all reference/positive/negative gates.

    Witnesses are already verified validation assets, not LLM answers. The normal
    LLM input workflow remains available when the existing input pool is exhausted.
    """
    old = read_bundle(qid,image=image)
    if not old:
        raise ValueError('repair requires an existing verified supplementary corpus')
    cases = deepcopy(old['cases'])
    generated = deepcopy(old['generated_cases'])
    keys = {sha(c['args']) for c in cases}
    added = []
    for asset in row['fixtures']:
        if asset['role']=='incorrect' and asset['state']=='survived' and asset.get('non_equivalent_verified'):
            args = asset['witness']
            if sha(args) not in keys:
                case = {'args':args,'expected':contracts.answer(qid,args)}
                added.append(case);cases.append(case);generated.append(case);keys.add(sha(args))
    if not added:
        return row
    candidate = audit.audit(qid,cases,old['languages'],image,cache_dir=cache_dir,check_cancel=check_cancel)
    save(Path(cache_dir).parent/'repair_attempts'/f'{qid}-{sha(candidate)}.json',candidate)
    if not candidate['passed']:
        raise ValueError('candidate repair failed a reference/positive/functional gate; not published')
    # Store evidence for the exact publication, rather than projecting counts
    # from the larger official-example/witness regression run.
    gates=[]
    import tempfile
    with tempfile.TemporaryDirectory(prefix='mci_repair_reference_') as folder:
        for language in old['languages']:
            code=Path(folder)/f'{qid}_{KEY_TO_LABEL[language]}_1.txt'
            code.write_text(load_reference(qid,language),encoding='utf-8')
            verdict=audited_judging.run(code,cases,check_cancel=check_cancel)
            if verdict['ac_status']!='Accepted':
                raise ValueError('exact published corpus reference gate failed; not published')
            gates.append({'language':language,'state':verdict['state'],'status':verdict['ac_status'],
                          'total':verdict['total_testcases'],'correct':verdict['total_correct'],'dropped':0,
                          'source':'exact_published_corpus_execution','verdict':audited_judging.public_verdict(verdict)})
    check_cancel()
    with lock(qid,CORPUS_DIR):
        current = read_bundle(qid,image=image)
        if not current or current['cases_sha256'] != old['cases_sha256']:
            raise ValueError('corpus changed during repair; not published')
        revised = deepcopy(old)
        revised.update(cases=cases,generated_cases=generated,cases_sha256=sha(cases),generated_sha256=sha(generated),
                       parent_cases_sha256=old['cases_sha256'])
        revised['gates'] = gates
        revised.setdefault('correctness_repairs',[]).append({'version':audit.VERSION,
            'source':'reviewed_regression_witness','added':added,'parent_cases_sha256':old['cases_sha256'],
            'report_sha256':candidate['report_sha256']})
        # Keep the old publication as a recoverable local snapshot.
        save(CORPUS_DIR/'history'/f'{qid}-{old["cases_sha256"]}.json',old)
        save(CORPUS_DIR/f'{qid}.json',revised)
    candidate['repair'] = {'added':len(added),'parent_cases_sha256':old['cases_sha256'],
                           'source':'reviewed_regression_witness'}
    candidate.pop('report_sha256',None);candidate['report_sha256']=sha(candidate)
    return candidate


def record_audit(row,cases,image):
    """A read-only recheck must not deactivate an unchanged passing publication."""
    previous=audit.receipt(row['qid'],cases,image)
    audit.save_receipt(row,promoted=bool(previous and previous.get('promoted') and row['passed']))


def write_report(folder, rows, errors):
    summary = {'version':audit.VERSION,'qids':[r['qid'] for r in rows],
               'passed':not errors and bool(rows) and all(r['passed'] for r in rows),
               'incorrect_total':sum(r['summary']['incorrect_total'] for r in rows),
               'killed':sum(r['summary']['killed'] for r in rows),
               'survived':sum(r['summary']['survived'] for r in rows),
               'pending':sum(r['summary']['pending'] for r in rows),
               'correct_total':sum(r['summary']['correct_total'] for r in rows),
               'correct_passed':sum(r['summary']['correct_passed'] for r in rows),
               'errors':errors,'questions':[{k:r[k] for k in ('qid','passed','summary','scope','answer_checks')} for r in rows],
               'notice':'Detection of these reviewed faults is not a correctness probability or selection-policy accuracy.'}
    save(folder/'summary.json',summary)
    lines=['# 15 题判题正确性审计','',
           '错误检出率仅针对有合法反例、真实执行证明非等价的回归程序，不是代码正确率。',
           '历史正式结果未改写；超出独立答案范围的用例明确单列。','',
           '| 题号 | 通过 | 错误检出 | 存活 | 待核实 | 正确改写 | 独立答案核验 | 范围外 |',
           '|---|---|---|---|---|---|---|---|']
    for r in rows:
        s=r['summary'];a=r['answer_checks']
        lines.append(f"| q{r['qid']} | {r['passed']} | {s['killed']}/{s['incorrect_total']} | {s['survived']} | {s['pending']} | {s['correct_passed']}/{s['correct_total']} | {a['oracle_checked']} | {a['outside_oracle_scope']} |")
    for error in errors:
        lines.append(f'- 未完成：{error}')
    lines += ['', '每题 JSON 保存反例、独立答案、执行判定、参考解门禁、判定配置和源码指纹；fixtures/ 保存实际执行源码。']
    (folder/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['audit','repair','verify'])
    ap.add_argument('--qids',default=','.join(map(str,contracts.QIDS)))
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    qids=sorted({int(q) for q in args.qids.split(',') if q.strip()})
    if not qids or not set(qids)<=set(contracts.QIDS):
        ap.error('only the 15 reviewed questions are supported in this iteration')
    if args.action=='verify' and set(qids)!=set(contracts.QIDS):
        ap.error('activation requires the complete set of 15 reviewed questions')
    image=image_digest();runner.DOCKER_IMAGE=image
    folder=args.output;folder.mkdir(parents=True,exist_ok=True)
    cache=folder/'executions'
    rows=[];errors=[]
    for qid in qids:
        try:
            bundle=read_bundle(qid,image=image)
            if not bundle:raise ValueError('verified supplementary corpus missing or stale')
            cases=load_cases(qid)
            for asset in fixtures(qid):
                p=folder/'fixtures'/f'{asset["id"]}.txt';p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text(asset['code'],encoding='utf-8')
            print(f'q{qid}: audit {len(cases)} inputs, languages {bundle["languages"]}',flush=True)
            row=audit.audit(qid,cases,bundle['languages'],image,cache_dir=cache,
                            on_event=lambda e:print(json.dumps(e),flush=True))
            if args.action=='repair' and not row['passed']:
                row=repair(qid,row,image,cache)
            save(folder/f'q{qid}.json',row)
            record_audit(row,load_cases(qid),image)
            rows.append(row)
            print(qid,row['summary'],flush=True)
        except Exception as error:
            errors.append(f'q{qid}: {type(error).__name__}: {error}')
            save(folder/f'q{qid}-blocked.json',{'qid':qid,'state':'blocked','reason':errors[-1]})
            print(errors[-1],flush=True)
        write_report(folder,rows,errors)
    summary=write_report(folder,rows,errors)
    if args.action=='verify' and summary['passed'] and len(rows)==len(contracts.QIDS):
        for row in rows:audit.save_receipt(row,promoted=True)
        print('Activated full-corpus-executed-v2 for 15 reviewed questions',flush=True)
    print(json.dumps({k:v for k,v in summary.items() if k!='questions'},ensure_ascii=False),flush=True)
    if not summary['passed']:raise SystemExit(1)


if __name__=='__main__':main()
