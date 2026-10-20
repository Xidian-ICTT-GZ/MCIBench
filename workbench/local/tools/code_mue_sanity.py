"""Clearly separated controlled common-wrong example, using actual sandbox outputs."""
from pathlib import Path
import tempfile
from local.harness import runner
from local.harness.identity import image_digest
from local.judge import judge_one
from local.lab.behavior import observe, sha
from local.lab.execution import CachedExecution
from local.lab.metrics import analyze
from local.tools.gap_workflow import save


def main():
    runner.DOCKER_IMAGE=image_digest()
    probes=[{'args':{'values':[1,1]}},{'args':{'values':[8,1,5,2,6]}}]
    validation=[{'args':{'values':[7,3]},'expected':9}]
    sources=['class Solution:\n    def maxScoreSightseeingPair(self, values):\n        return 1\n',
             'class Solution:\n    def maxScoreSightseeingPair(self, values):\n        answer = 0 + 1\n        return answer\n']
    with tempfile.TemporaryDirectory() as tmp:
        executor=CachedExecution(Path(tmp)/'cache',runner.DOCKER_IMAGE)
        candidates=[]
        for i,code in enumerate(sources):
            outputs=[observe(1014,'python3',code,p,executor=executor) for p in probes]
            path=Path(tmp)/'1014_Python3_1.txt';path.write_text(code,encoding='utf-8')
            verdict=judge_one(path,'gen',1,'docker',cases_override=validation,run_timeout_s=5)
            candidates.append({'id':str(i),'code':code,'code_sha256':sha(code),'outcomes':outputs,'verdict':verdict})
        metrics=analyze(candidates)
    if metrics['uncertainty']>1e-8 or any(c['verdict']['ac_status']!='Wrong Answer' for c in candidates):
        raise RuntimeError('controlled common-wrong sanity evidence did not reproduce')
    result={'scope':'manual controlled sanity, excluded from natural model statistics', 'image':runner.DOCKER_IMAGE,
            'qid':1014,'probes':probes,'independent_validation':validation,'metrics':metrics,'candidates':candidates,
            'conclusion':'U=0 despite both implementations failing independent validation; behavioral consensus is not correctness'}
    save(Path('local/results/six_improvements/code-mue-pilot/controlled-common-wrong.json'),result)
    print('controlled common-wrong: U=0, both Wrong Answer; excluded from natural model results')


if __name__=='__main__':main()
