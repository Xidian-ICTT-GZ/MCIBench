"""Actual execution of clearly labeled manual UI fixtures, never model research data."""
from pathlib import Path
import tempfile

from local.common import load_reference
from local.harness import runner
from local.harness.identity import image_digest
from local.judge import judge_one
from local.lab.behavior import observe, sha
from local.lab.execution import CachedExecution
from local.lab.metrics import analyze
from local.lab.storage import Store
from local.tools.gap_workflow import save


def main():
    store = Store(Path('local/dashboard/packages/server/data/lab.sqlite3'))
    title = '功能验收样例 · 人工代码（非模型采样）'
    existing = next((j for j in store.jobs() if j['title'] == title),None)
    if existing and store.job(existing['id'])['result'].get('source_kind') != 'manual_qa_not_model_sampling':
        raise ValueError('existing record is not this manual fixture')
    probes = [{'args':{'values':[1,1]}},{'args':{'values':[8,1,5,2,6]}},{'args':{'values':[5,5]}}]
    validation = [{'args':{'values':[7,3]},'expected':9}]
    codes = [load_reference(1014,'python3'),
             'class Solution:\n    def maxScoreSightseeingPair(self, values):\n        return 1\n',
             'class Solution:\n    def maxScoreSightseeingPair(self, values):\n        raise ValueError("manual failure fixture")\n']
    runner.DOCKER_IMAGE = image_digest()
    executor = CachedExecution(Path('local/results/six_improvements/matrix-qa-artifacts'),runner.DOCKER_IMAGE)
    candidates = []
    for i,code in enumerate(codes):
        outcomes = [observe(1014,'python3',code,probe,executor=executor) for probe in probes]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'1014_Python3_1.txt';path.write_text(code,encoding='utf-8')
            verdict = judge_one(path,'gen',1,'docker',cases_override=validation,run_timeout_s=5)
        candidates.append({'id':f'manual-qa-{i+1}','index':i+1,'code':code,'raw':code,'code_sha256':sha(code),
                           'source_kind':'manual_qa_not_model_sampling','outcomes':outcomes,'generation_state':'succeeded',
                           'verdict':{k:verdict[k] for k in ('ac_status','runtime','memory','total_correct','total_testcases')},
                           'validation_passed':verdict['ac_status']=='Accepted'})
    metrics = analyze(candidates)
    profile = store.profiles()[-1]['id']
    spec = {'qids':[1014],'model_ids':[profile],'languages':['python3'],'task':'gen','source_language':'python3',
            'num_candidates':3,'probe_count':3,'temperature':.7,'probe_strategy':'balanced','metamorphic_checks':False}
    job = existing or store.create_job(title,spec)
    result = {'source_kind':'manual_qa_not_model_sampling','notice':'人工构造代码并真实执行，仅用于矩阵界面验收，不纳入模型研究或正式成绩。',
              'inputs':[{'qid':1014,'probes':probes,'probe_sha256':sha(probes),'validation_count':1}],
              'groups':[{'qid':1014,'model_id':profile,'model_name':'人工验收 · 非模型生成','language':'python3',
                         'candidates':candidates,'metrics':metrics,'probe_count':3,'validation_count':1,'local_pass_rate':1/3}],
              'cross_language':[]}
    store.write_job(job['id'],state='completed',stage='人工代码功能验收；非模型采样，不能复制本结果作为模型成绩',progress=100,result=result)
    save(Path('local/results/six_improvements/matrix-qa.json'),store.job(job['id']))
    print(job['id'],metrics['matrix'],flush=True)


if __name__ == '__main__':
    main()
