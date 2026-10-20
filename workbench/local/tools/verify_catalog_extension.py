"""Real sandbox integration with explicit reference replay, no model API or production jobs."""
import argparse
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from local.common import load_reference, save_json
from local.lab.catalog import catalog
from local.lab.jobs import Engine, validate_spec
from local.lab.storage import Store, ACTIVE


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=Path('local/results/catalog-extension-integration.json'))
    args = ap.parse_args()
    report = {'mode': 'reference_replay_not_model_generation', 'model_api_calls': 0,
              'catalog_counts': catalog()['counts'], 'jobs': []}
    with tempfile.TemporaryDirectory(prefix='mci_catalog_replay_') as tmp:
        store = Store(Path(tmp) / 'replay.sqlite3')
        profile = store.save_profile({'name': 'reference replay fixture', 'model_name': 'fixture', 'api_url': 'http://localhost:1/v1'})
        engine = Engine(store)
        try:
            for task, languages in [('gen', ['python3', 'cpp']), ('trans', ['cpp'])]:
                spec = validate_spec({'qids': [20], 'model_ids': [profile['id']], 'task': task,
                                      'languages': languages, 'source_language': 'python3',
                                      'num_candidates': 2, 'probe_count': 2}, store)
                job = store.create_job('reference replay fixture', spec)
                fixtures = []
                for lang in languages:
                    code = load_reference(20, lang)
                    fixtures.extend([{'raw': code, 'code': code, 'finish_reason': 'stop'},
                                     {'raw': code, 'code': code, 'finish_reason': 'stop'}])
                with patch('local.lab.jobs.generate', side_effect=fixtures) as generator:
                    engine.start(job['id'])
                    deadline = time.monotonic() + 240
                    while store.job(job['id'])['state'] in ACTIVE:
                        if time.monotonic() > deadline:
                            engine.cancel(job['id'])
                            raise RuntimeError('reference replay exceeded integration deadline')
                        time.sleep(.2)
                done = store.job(job['id'])
                if done['state'] != 'completed':
                    raise RuntimeError(done.get('error') or done['state'])
                groups = done['result']['groups']
                if any(g['local_pass_rate'] != 1 or g['metrics']['uncertainty'] != 0
                       or g['corpus_evidence']['scope'] != 'extension' for g in groups):
                    raise RuntimeError('expanded question replay lost behavior/correctness/evidence')
                report['jobs'].append({'task': task, 'qid': 20, 'state': done['state'],
                                       'candidates': generator.call_count,
                                       'groups': [{k: g[k] for k in ('language', 'local_pass_rate', 'validation_count', 'probe_count', 'metrics', 'corpus_evidence')} for g in groups]})
                save_json(args.out, report)
                print(task, 'completed', generator.call_count, 'reference candidates', flush=True)
        finally:
            engine.close()
    print(json.dumps({'counts': report['catalog_counts'], 'jobs': len(report['jobs']), 'model_api_calls': 0}), flush=True)


if __name__ == '__main__':
    main()
