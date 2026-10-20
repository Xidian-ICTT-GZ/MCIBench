"""Exploratory study metrics with ties and question-cluster uncertainty."""
from collections import Counter
from difflib import SequenceMatcher
import math
import random

from local.lab.metrics import token


def scores(group):
    candidates, matrix = group['candidates'], group['metrics']['matrix']
    n = len(candidates)
    signatures = [tuple(token(o, candidate=i, probe=p) for p,o in enumerate(c['outcomes'])) for i,c in enumerate(candidates)]
    counts = Counter(signatures)
    entropy = -sum((v/n)*math.log(v/n) for v in counts.values())/math.log(n)
    pairs = [1-SequenceMatcher(None, a['code'], b['code'], autojunk=False).ratio()
             for i,a in enumerate(candidates) for b in candidates[:i]]
    return {'spectral_u': group['metrics']['uncertainty'],
            'mean_disagreement': 1-group['metrics']['mean_pairwise_agreement'],
            'signature_entropy': entropy, 'text_variation': sum(pairs)/len(pairs)}


def risk_metrics(risks, errors):
    if len(risks) != len(errors) or not risks:
        raise ValueError('risk and error labels must align')
    n, positives = len(errors), sum(errors)
    if any(e not in (0,1) for e in errors) or any(not math.isfinite(r) for r in risks):
        raise ValueError('invalid risk or label')
    # AUROC pairwise comparison gives average-rank handling of ties.
    pos = [r for r,e in zip(risks,errors) if e]
    neg = [r for r,e in zip(risks,errors) if not e]
    auc = sum((a>b)+.5*(a==b) for a in pos for b in neg)/(len(pos)*len(neg)) if pos and neg else None
    rows = sorted(zip(risks,errors), reverse=True)
    ap, seen, found = 0., 0, 0
    for threshold in sorted(set(risks), reverse=True):
        tied = [e for r,e in rows if r == threshold]
        seen += len(tied); found += sum(tied)
        ap += (sum(tied)/positives)*(found/seen) if positives else 0
    # AUPRC/AP is uninformative with only one class; explicitly unavailable.
    ap = ap if pos and neg else None
    seen, found, areas, curve = 0, 0., [], []
    for threshold in sorted(set(risks)):
        tied = [e for r,e in zip(risks,errors) if r == threshold]
        m, count = len(tied), sum(tied)
        for j in range(1,m+1):
            risk = (found+j*count/m)/(seen+j)
            areas.append(risk)
            curve.append({'coverage':(seen+j)/n, 'risk':risk, 'threshold':threshold})
        seen += m; found += count
    return {'n':n, 'errors':positives, 'error_rate':positives/n, 'auroc':auc, 'auprc_ap':ap,
            'aurc':sum(areas)/n, 'coverage_risk':curve,
            'unavailable_reason':'correctness labels contain only one class' if not pos or not neg else None,
            'tie_policy':'equal-risk coverage order averaged; AP grouped by equal threshold'}


def clustered_interval(rows, function, *, seed=20261014, repeats=1000):
    clusters = sorted({r['qid'] for r in rows})
    if not clusters:
        return {'low':None, 'high':None, 'valid_draws':0, 'total_draws':repeats}
    rng, values = random.Random(seed), []
    for _ in range(repeats):
        chosen = [rng.choice(clusters) for _ in clusters]
        sample = [r for q in chosen for r in rows if r['qid'] == q]
        value = function(sample)
        if value is not None and math.isfinite(value):
            values.append(value)
    values.sort()
    return {'low':values[int(.025*(len(values)-1))] if values else None,
            'high':values[int(.975*(len(values)-1))] if values else None,
            'valid_draws':len(values), 'total_draws':repeats, 'cluster':'question'}


def report(rows):
    output = {}
    for split in ('all','dev','test'):
        subset = [r for r in rows if split == 'all' or r['split'] == split]
        if not subset:
            continue
        metrics = {}
        for name in ('spectral_u','mean_disagreement','signature_entropy','text_variation'):
            metrics[name] = risk_metrics([r['scores'][name] for r in subset], [r['selected_error'] for r in subset])
            metrics[name]['auroc_ci95'] = clustered_interval(subset, lambda sample:
                risk_metrics([r['scores'][name] for r in sample],[r['selected_error'] for r in sample])['auroc'])
            error_clusters = len({r['qid'] for r in subset if r['selected_error']})
            correct_clusters = len({r['qid'] for r in subset if not r['selected_error']})
            if min(error_clusters,correct_clusters) < 2:
                ci = metrics[name]['auroc_ci95']
                ci['conditional_bounds'] = {'low':ci['low'],'high':ci['high']}
                ci.update(low=None,high=None,reason='fewer than two independent question clusters for one class')
            metrics[name]['error_question_clusters'] = error_clusters
        accuracy = sum(1-r['selected_error'] for r in subset)/len(subset)
        available = [r for r in subset if r['any_correct']]
        output[split] = {'groups':len(subset), 'questions':len({r['qid'] for r in subset}), 'risk_metrics':metrics,
                        'center_accuracy':accuracy,
                        'center_accuracy_ci95':clustered_interval(subset, lambda s:sum(1-r['selected_error'] for r in s)/len(s)),
                        'random_selection_expected_accuracy':sum(r['random_accuracy'] for r in subset)/len(subset),
                        'mean_agreement_center_accuracy':sum(r['mean_center_correct'] for r in subset)/len(subset),
                        'correct_candidate_available_groups':len(available),
                        'center_accuracy_given_any_correct':sum(1-r['selected_error'] for r in available)/len(available) if available else None,
                        'low_u_common_wrong':sum(r['scores']['spectral_u'] <= .1 and not r['any_correct'] for r in subset),
                        'low_u_selected_wrong':sum(r['scores']['spectral_u'] <= .1 and r['selected_error'] for r in subset),
                        'low_u_groups':sum(r['scores']['spectral_u'] <= .1 for r in subset)}
    output['languages'] = {lang: {'groups':len(s), 'center_accuracy':sum(1-r['selected_error'] for r in s)/len(s),
                                'generated_codes':sum(r['candidate_count'] for r in s)}
                           for lang in sorted({r['language'] for r in rows}) if (s := [r for r in rows if r['language'] == lang])}
    return output
