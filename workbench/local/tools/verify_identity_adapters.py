"""Real sandbox checks of node identity, Master calls and dataframe dtype.

Negative fixtures are adapter gates, not the 15-question mutation benchmark.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.common import load_reference
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import native_python,native_adapters,problem_packages,portable_judging
from local.lab.behavior import sha


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'image':runner.DOCKER_IMAGE,
        'adapter_sha256':sha(Path(native_python.__file__).read_text(encoding='utf8')),'checks':[]}
    def check(qid,label,code,expected_status,*,native=True):
        descriptor=problem_packages.describe(qid);cases=descriptor['official'];comparison=descriptor['comparison']
        if native:
            plan={'kind':'bridge',**native_python.bridge(qid,descriptor)}
            plan['adapter_sha256']=sha({'prefix':plan['prefix'],'suffix':plan['suffix']})
            result=native_adapters.execute(qid,'python3',code,cases,comparison,plan)
        else:result=portable_judging.execute(qid,'python3',code,cases,comparison)
        passed=result['ac_status']==expected_status
        report['checks'].append({'qid':qid,'label':label,'source_sha256':sha(code),'expected_status':expected_status,
            'actual_status':result['ac_status'],'passed':passed,'verdict':result})
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(qid,label,result['ac_status'],'PASS' if passed else 'FAIL',flush=True)
        if not passed:raise SystemExit(1)
    for qid in (116,117,142,160,843):
        try:code=load_reference(qid,'python3');label='repository reference with real native interface'
        except OSError:
            path=native_adapters.DATA_DIR/str(qid)/'python3.json'
            if not path.exists():path=path.with_name('python3.pending.json')
            if path.exists():
                cached=json.loads(path.read_text(encoding='utf8'));code=cached['reference_code']
                if sha(code)!=cached['reference_sha256']:raise ValueError('saved reference source drift')
                label='saved independent native program; acceptance checked by this run'
            elif qid==116:
                code='''class Solution:
    def connect(self,root):
        level=[root] if root else []
        while level:
            for i,node in enumerate(level):node.next=level[i+1] if i+1<len(level) else None
            level=[child for node in level for child in (node.left,node.right) if child is not None]
        return root
'''
                label='reviewed next-pointer adapter fixture (not a model sample)'
            else:raise
        check(qid,label,code,'Accepted')
    check(142,'fresh equal-valued node is not the cycle entry',
        'class Solution:\n    def detectCycle(self,head):return ListNode(2)','Runtime Error')
    check(160,'first equal-valued node is not the shared node',
        'class Solution:\n    def getIntersectionNode(self,a,b):return a','Wrong Answer')
    check(117,'breadth-first values without actual next links are insufficient',
        'class Solution:\n    def connect(self,root):return root','Runtime Error')
    check(843,'no guess calls cannot report success',
        'class Solution:\n    def findSecretWord(self,words,master):pass','Wrong Answer')
    check(2886,'integral floating values do not prove integer dtype',
        "def solve(data):return data['students']",'Wrong Answer',native=False)
    print('identity/type adapter failures: 0')


if __name__=='__main__':main()
