"""Explicit diagnostic probes; proposals and configuration variants never publish."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.tools import gap_workflow as w


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('kind',choices=['forward','stack','budget','ubsan'])
    ap.add_argument('--job',type=Path,required=True)
    ap.add_argument('--qids',default='2580,2597')
    ap.add_argument('--samples',type=int,default=60)
    ap.add_argument('--branch',choices=['wa','crash','performance'],default='wa')
    args=ap.parse_args();args.job=args.job.resolve();args.job.mkdir(parents=True,exist_ok=True)
    from local.harness import runner
    from local.harness.identity import image_digest,result_errors
    runner.DOCKER_IMAGE=image_digest()
    if args.kind=='ubsan':
        # A legal n=1 query isolates the unconditional signed 1 << 31 shift.
        # Compilation variants run in separate containers and never enter
        # judge/import/publication paths or change the production image.
        job=w.plan();rows=[]
        probe='''import json,subprocess,time
import sys
flags=json.loads(sys.argv[1])
compiled=subprocess.run(['gcc','-O2',*flags,'/input/driver.c','-o','/tmp/probe'],capture_output=True,text=True,timeout=120)
if compiled.returncode:
    print(json.dumps({'compile_exit':compiled.returncode,'stderr':compiled.stderr}));sys.exit(0)
started=time.monotonic()
try:
    result=subprocess.run(['/tmp/probe'],capture_output=True,text=True,timeout=5)
    print(json.dumps({'compile_exit':0,'run_exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'wall_s':time.monotonic()-started}))
except subprocess.TimeoutExpired:
    print(json.dumps({'compile_exit':0,'timeout':True}))
except OSError as error:
    print(json.dumps({'compile_exit':0,'infrastructure_error':str(error)}))
'''
        for t in job['tasks']:
            s=t['slot']
            if s['qid']!=2438 or s['lang']!='c' or s['klass']!='false_ac':continue
            w.assert_current(s);source=w.code_path(s);raw=source.read_bytes()
            directory=args.job/t['id'];directory.mkdir(parents=True,exist_ok=True)
            (directory/'probe.py').write_text(probe,encoding='utf-8')
            driver='#include <stdlib.h>\n#include <stdio.h>\n'+raw.decode('utf-8')+'''
int main(void) { int query[2]={0,0}; int* queries[1]={query}; int columns[1]={2}; int size=0;
int* answer=productQueries(1,queries,1,columns,&size);
if(size!=1)return 3; printf("[%d]\\n",answer[0]); free(answer); return 0; }
'''
            (directory/'driver.c').write_text(driver,encoding='utf-8')
            items=[]
            for flags in [[],['-fsanitize=undefined','-fno-sanitize-recover=undefined']]:
                command=['docker','run','--rm','--network','none','--user','65534:65534',
                    '--cap-drop','ALL','--security-opt','no-new-privileges','--read-only',
                    '--pids-limit','64','--cpus','1','--memory','1024m',
                    '--tmpfs','/tmp:rw,exec,nosuid,size=536870912,mode=1777',
                    '-v',f'{directory.resolve()}:/input:ro',runner.DOCKER_IMAGE,
                    'python3','-I','/input/probe.py',json.dumps(flags)]
                result=subprocess.run(command,capture_output=True,text=True,timeout=150)
                observation=json.loads(result.stdout) if result.returncode==0 else None
                items.append({'flags':flags,'command':command,'docker_exit':result.returncode,
                              'docker_stderr':result.stderr,'observation':observation})
            if source.read_bytes()!=raw:raise RuntimeError('original code changed')
            rows.append({'slot':s,'code_sha256':w.sha(raw),'driver_sha256':w.sha(driver.encode()),
                         'input':{'n':1,'queries':[[0,0]]},'expected':[1],
                         'items':items,'diagnostic_only':True,'same_lc_source_confirmed':False,
                         'formal_results_modified':False})
            w.save(args.job/'probe.json',rows)
            print(t['id'],[i['observation'].get('run_exit') if i['observation'] else None for i in items],flush=True)
        return
    if args.kind=='forward':
        job=w.plan();w.save(args.job/'job.json',job)
        for q in sorted({int(x) for x in args.qids.split(',') if x}):
            t=next((t for t in job['tasks'] if t['branch']==args.branch and t['slot']['qid']==q),None)
            if t is None:continue
            directory=args.job/t['id'];directory.mkdir()
            print(t['id'],flush=True)
            config=SimpleNamespace(job=args.job,samples=args.samples,seed=20261013,publish=False)
            try:w.assert_current(t['slot']);t.update(w.repair_wa(t,job,directory,config))
            except Exception as exc:t.update(status='blocked',error=f'{type(exc).__name__}: {exc}')
            w.save(args.job/'job.json',job);print(' ->',t['status'],flush=True)
        return
    job=w.plan();q=2588 if args.kind=='stack' else 2597
    slot=next(t['slot'] for t in job['tasks'] if t['slot']['qid']==q and t['slot']['klass']=='false_wa'
              and t['slot']['lang']==('c' if args.kind=='stack' else 'python3'))
    w.assert_current(slot);source=w.code_path(slot);raw=source.read_bytes()
    cp=w.CORPUS/str(q)/'cases.json';original=cp.read_bytes();cases=json.loads(original)
    from local.judge import judge_one
    items=[]
    for setting in ([8,64] if args.kind=='stack' else [5,5,5,10,20]):
        commands=[];actual_popen=subprocess.Popen
        def launch(cmd,*a,**kw):
            if isinstance(cmd,(list,tuple)) and len(cmd)>1 and Path(cmd[0]).stem.lower()=='docker' and cmd[1]=='run':
                cmd=list(cmd[:2])+['--ulimit',f'stack={setting*1024*1024}:{setting*1024*1024}']+list(cmd[2:])
                commands.append(cmd)
            return actual_popen(cmd,*a,**kw)
        with patch.object(subprocess,'Popen',launch) if args.kind=='stack' else patch.object(subprocess,'Popen',actual_popen):
            result=judge_one(source,'gen',1000,'docker',5 if args.kind=='stack' else setting,cases_override=cases)
        errors=result_errors(result,{'config':{'output_protocol':1,'supervisor_protocol':2,
                                              'asan_confirm':True},'slot':{'lang':slot['lang']}})
        items.append({'setting':setting,'unit':'stack MiB' if args.kind=='stack' else 'seconds',
                      'result':result,'validation_errors':errors,'override_commands':commands})
        if source.read_bytes()!=raw or cp.read_bytes()!=original:raise RuntimeError('original input changed')
        w.save(args.job/'probe.json',{'kind':args.kind,'slot':slot,'code_sha256':w.sha(raw),
                                    'corpus_sha256':w.sha(original),'items':items,
                                    'diagnostic_only':True,'formal_results_modified':False})
        print(setting,result['ac_status'],flush=True)


if __name__=='__main__':main()
