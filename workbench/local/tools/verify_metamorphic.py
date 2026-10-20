"""Reference execution gates for the reviewed metamorphic relations."""
import argparse
import json
from pathlib import Path

from local.common import LANGS, load_reference
from local.harness import runner
from local.harness.identity import image_digest
from local.lab.behavior import observe, sha
from local.lab.metamorphic import proposals, evaluate
from local.tools.gap_workflow import save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    runner.DOCKER_IMAGE = image_digest()
    probes = {1014: [{'args': {'values': [8, 1, 5, 2, 6]}}], 1957: [{'args': {'s': 'aaabaaaa'}}]}
    evidence = {'image': runner.DOCKER_IMAGE, 'relations_sha256': sha(Path(__file__).resolve().parents[1].joinpath('lab/metamorphic.py').read_text(encoding='utf-8')),
                'label_source': 'reference_relation_verification', 'rows': []}
    save(args.out, evidence)
    for qid, cases in probes.items():
        variants = proposals(qid, cases)
        for language in LANGS:
            code = load_reference(qid, language)
            base = observe(qid, language, code, cases[0])
            for proposal in variants:
                outcome = observe(qid, language, code, proposal['input'])
                result = evaluate(proposal, base, outcome)
                evidence['rows'].append({'qid': qid, 'language': language, 'code_sha256': sha(code), 'result': result})
                save(args.out, evidence)
                print(qid, language, proposal['name'], result['state'], flush=True)
                if result['state'] != 'passed':
                    raise RuntimeError('metamorphic reference gate failed')
    evidence['completed'] = True
    save(args.out, evidence)


if __name__ == '__main__':
    main()
