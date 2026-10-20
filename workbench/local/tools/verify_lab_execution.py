"""Actual eight-language cold/warm equivalence and execution-phase measurements."""
import argparse
from pathlib import Path
import statistics
import tempfile
import threading
import time
from unittest.mock import patch

from local.common import LANGS, load_reference
from local.harness import runner
from local.harness.identity import image_digest
from local.lab.behavior import observe, sha
from local.lab.execution import CachedExecution
from local.tools.gap_workflow import save
from local.lab.jobs import Engine, validate_spec
from local.lab.storage import Store


def semantic(o):
    return {k: o.get(k) for k in ('kind', 'status', 'value', 'semantic_key', 'exception_type')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    runner.DOCKER_IMAGE = image_digest()
    evidence = {'image': runner.DOCKER_IMAGE, 'rows': [], 'execution_outputs_cached': False,
                'fresh_container_per_input': True, 'max_sandbox_concurrency': 1}
    with tempfile.TemporaryDirectory(prefix='mci_artifact_gates_') as tmp:
        executor = CachedExecution(Path(tmp), runner.DOCKER_IMAGE)
        evidence['cache_binding'] = executor.binding
        evidence['execution_sha256'] = sha(Path(__file__).resolve().parents[1].joinpath('lab/execution.py').read_text(encoding='utf-8'))
        probe = {'args': {'values': [8, 1, 5, 2, 6]}}
        for language in LANGS:
            code = load_reference(1014, language)
            baseline = observe(1014, language, code, probe)
            outcomes = [observe(1014, language, code, probe, executor=executor) for _ in range(3)]
            if any(semantic(o) != semantic(baseline) for o in outcomes):
                raise RuntimeError('cold/warm semantics differ from formal execution')
            if language in ('c', 'cpp', 'csharp', 'java', 'golang', 'rust'):
                if [o['timing']['cache_mode'] for o in outcomes] != ['cold', 'warm', 'warm']:
                    raise RuntimeError('compiled artifact reuse did not occur')
            row = {'language': language, 'code_sha256': sha(code), 'baseline': baseline, 'runs': outcomes,
                   'cold_wall_ms': outcomes[0]['timing']['wall_ms'],
                   'warm_median_wall_ms': statistics.median(o['timing']['wall_ms'] for o in outcomes[1:])}
            evidence['rows'].append(row)
            save(args.out, evidence)
            print(language, 'equivalent', round(row['cold_wall_ms']), '->', round(row['warm_median_wall_ms']), flush=True)
        # Fresh Python process AND filesystem: file and module state must not leak.
        code = '''class Solution:
    def maxScoreSightseeingPair(self, values):
        from pathlib import Path
        p=Path('/w/state')
        old=p.exists()
        p.write_text('state')
        return 999 if old else 11
'''
        isolated = [observe(1014, 'python3', code, probe, executor=executor) for _ in range(2)]
        if [o.get('value') for o in isolated] != [11, 11]:
            raise RuntimeError('process/filesystem state leaked')
        timeout_code = 'class Solution:\n    def maxScoreSightseeingPair(self, values):\n        while True: pass\n'
        timed = observe(1014, 'python3', timeout_code, probe, executor=executor, timeout=.2)
        if timed['kind'] != 'timeout':
            raise RuntimeError('sandbox timeout no longer applies')
        resource_code = '''class Solution:
    def maxScoreSightseeingPair(self, values):
        import os
        from pathlib import Path
        flags = [os.getuid()==65534,
                 Path('/sys/fs/cgroup/memory.max').read_text().strip()=='1610612736',
                 Path('/sys/fs/cgroup/pids.max').read_text().strip()=='128',
                 Path('/sys/fs/cgroup/cpu.max').read_text().split()==['100000','100000'],
                 all(':' not in line or line.split(':')[0].strip()=='lo' for line in Path('/proc/net/dev').read_text().splitlines())]
        return sum((1<<i) for i,flag in enumerate(flags) if flag)
'''
        resource = observe(1014,'python3',resource_code,probe,executor=executor)
        if resource.get('value') != 31:
            raise RuntimeError('actual sandbox UID/cgroup/network limits differ')
        error_cases = [('cpp','class Solution { broken syntax };'),
                       ('javascript','var maxScoreSightseeingPair = function(values) { throw new TypeError("fixture"); };')]
        failures = []
        for language,code in error_cases:
            a=observe(1014,language,code,probe)
            b=observe(1014,language,code,probe,executor=executor)
            if semantic(a)!=semantic(b):
                raise RuntimeError('failure mapping differs')
            failures.append({'language':language,'baseline':a,'optimized':b})
        # Stub only generation; this cancellation exercises a real sandbox call.
        store=Store(Path(tmp)/'cancel.sqlite3')
        profile=store.save_profile({'name':'manual cancellation QA','model_name':'stub','api_url':'https://example.com','api_key':'test-only'})
        spec=validate_spec({'qids':[1014],'model_ids':[profile['id']],'languages':['python3'],'num_candidates':2,'probe_count':2},store)
        job=store.create_job('manual cancellation QA',spec)
        engine=Engine(store)
        entered,release=threading.Event(),threading.Event()
        actual_observe=observe
        calls=[]
        def held_observe(*args,**kwargs):
            calls.append(True)
            value=actual_observe(*args,**kwargs)
            entered.set()
            if not release.wait(10):
                raise RuntimeError('cancellation QA did not release')
            return value
        with patch('local.lab.jobs.generate',return_value={'code':load_reference(1014,'python3'),'raw':'manual stub'}),patch('local.lab.jobs.observe',side_effect=held_observe):
            engine.start(job['id'])
            if not entered.wait(20):
                release.set();engine.close();raise RuntimeError('cancellation sandbox did not finish')
            engine.cancel(job['id']);release.set();engine.close()
        cancelled=store.job(job['id'])
        if cancelled['state']!='cancelled' or len(calls)!=1:
            raise RuntimeError('cancellation scheduled extra sandbox calls')
        evidence.update(completed=True, isolation=isolated, timeout=timed, resource_limits=resource, failure_equivalence=failures,
                        cancellation={'state':cancelled['state'],'sandbox_calls':len(calls),'generation':'manual stub, no API call'})
        save(args.out, evidence)


if __name__ == '__main__':
    main()
