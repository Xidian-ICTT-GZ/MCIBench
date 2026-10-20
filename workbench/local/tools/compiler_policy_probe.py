"""Read-only compiler-policy diagnostics. Never publish verdicts or rewrite sources."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import tempfile
import time
import sqlite3

from local.common import load_reference, load_snippet, load_ft_test_qids
from local.harness import runner
from local.harness.identity import image_digest
from local.harness.output_drivers import render_output_driver
from local.harness.render import extract_plain_entry
from local.harness.typespec import parse_python_snippet
from local.harness.process_capture import capture
from local.judge import load_cases
from local.lab.behavior import sha
from local.tools.gap_workflow import code_path, save

BASE = ['-O2', '-Werror=implicit-int', '-Werror=implicit-function-declaration']
POLICIES = {'formal_flags': BASE, 'pointer_type_strict': BASE+['-Werror=incompatible-pointer-types']}


def compile_check(language, driver, image, flags):
    with tempfile.TemporaryDirectory(prefix='mci_compile_probe_') as tmp:
        path = Path(tmp)/('driver.c' if language=='c' else 'driver.cpp')
        path.write_text(driver,encoding='utf-8')
        command = ['docker','run','--rm','--network','none','--user','65534:65534',
                   '--memory',f'{runner.DOCKER_MEM_MB}m','--memory-swap',f'{runner.DOCKER_MEM_MB}m',
                   '--cpus','1','--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges',
                   '-v',f'{path.resolve()}:/input/{path.name}:ro',image,
                   'gcc' if language=='c' else 'g++',*flags,'-fsyntax-only','/input/'+path.name]
        started=time.perf_counter()
        result=capture(command,Path(tmp),150,stdout_limit=1024*1024,stderr_limit=2*1024*1024)
    stderr=result.stderr.decode('utf-8','replace')
    if result.returncode in (125,126,127) or runner._looks_like_infra_failure(stderr) or runner._looks_like_compiler_oom(stderr) or result.timed_out:
        raise runner.InfrastructureError('compiler policy probe incomplete: '+stderr[:500])
    return {'exit_code':result.returncode,'compiles':result.returncode==0,'stderr':stderr,
            'wall_ms':(time.perf_counter()-started)*1000,'flags':flags}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--accepted-dev',action='store_true',help='Read-only regression probe of existing dev C LC-Accepted sources')
    args=parser.parse_args()
    image=image_digest()
    evidence={'image':image,'scope':'diagnostic syntax-only, no production changes',
              'gcc14_source':'https://gcc.gnu.org/gcc-14/porting_to.html#incompatible-pointer-types',
              'same_lc_source_confirmed':False,'rows':[]}
    if args.out.exists():
        evidence=json.loads(args.out.read_bytes())
        if evidence['image']!=image:raise ValueError('diagnostic image changed')
    tasks=[(1338,'c','qwen3-8b-g-sft'),(1550,'cpp','glm-4'),(2535,'cpp','glm-4')]
    tasks += [(qid,'c','reference') for qid in load_ft_test_qids()]
    if args.accepted_dev:
        from local.tools.gap_workflow import DB
        with sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True) as con:
            tasks += [(qid,'c',model) for qid,model in con.execute("""SELECT s.qid,s.model FROM slots s
                JOIN problems p ON p.qid=s.qid WHERE s.lang='c' AND s.leetcode='Accepted'
                AND s.identity_status='current' AND s.lc_origin='submissions' AND s.local_origin='all_models'
                AND p.split='dev' ORDER BY s.qid,s.model""")]
        evidence['accepted_dev_requested']=True
    for qid,language,model in tasks:
        code=load_reference(qid,language) if model=='reference' else code_path(dict(qid=qid,model=model,lang=language,cand=1)).read_text(encoding='utf-8')
        sig=parse_python_snippet(load_snippet(qid,'python3'))
        from local.harness.typespec import PlainSig
        entry=extract_plain_entry(language,load_snippet(qid,language)) if isinstance(sig,PlainSig) else {}
        driver=render_output_driver(language,sig,entry,load_cases(qid)[:1],code)
        old=next((r for r in evidence['rows'] if (r['qid'],r['language'],r['model'])==(qid,language,model)),None)
        if old:
            if old['code_sha256']!=sha(code) or old['driver_sha256']!=sha(driver):raise ValueError('diagnostic source changed')
            continue
        profiles=POLICIES if language=='c' else {'formal_flags':BASE}
        checks={name:compile_check(language,driver,image,flags) for name,flags in profiles.items()}
        evidence['rows'].append({'qid':qid,'language':language,'model':model,'code_sha256':sha(code),
                                 'driver_sha256':sha(driver),'checks':checks})
        save(args.out,evidence)
        print(qid,language,model,{name:r['compiles'] for name,r in checks.items()},flush=True)
    evidence['completed']=True
    evidence['reference_regressions']=[r['qid'] for r in evidence['rows'] if r['model']=='reference'
               and r['checks']['formal_flags']['compiles'] and not r['checks']['pointer_type_strict']['compiles']]
    if args.accepted_dev:
        accepted={(q,lang,m) for q,lang,m in tasks[103:]}
        evidence['accepted_dev_regressions']=[{'qid':r['qid'],'model':r['model']} for r in evidence['rows']
            if (r['qid'],r['language'],r['model']) in accepted and r['checks']['formal_flags']['compiles']
            and not r['checks']['pointer_type_strict']['compiles']]
    save(args.out,evidence)


if __name__=='__main__':main()
