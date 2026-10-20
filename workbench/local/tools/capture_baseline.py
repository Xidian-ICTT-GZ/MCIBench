"""Read-only baseline capture and consistent SQLite backup for the system handoff.

Evidence goes to local/docs/reviews/20261018-system-handoff/baseline/.
The lab profile table is only counted, never queried, so no credential is read.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

from local.harness.identity import judge_source_closure, image_digest

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / 'local/docs/reviews/20261018-system-handoff/baseline'
SERVER_DIR = REPO / 'local/dashboard/packages/server'
DATA_DIR = SERVER_DIR / 'data'
LAB_DB = DATA_DIR / 'lab.sqlite3'
PREV_BASELINE = REPO / 'local/docs/reviews/20261015-correctness-15/baseline.json'
ACTIVE_STATES = ('queued', 'generating', 'evaluating', 'cancelling')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def git(args, cwd=REPO) -> str:
    try:
        out = subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True, encoding='utf-8')
        return out.stdout.strip() if out.returncode == 0 else '<error %s>' % out.returncode
    except Exception as error:                                    # noqa: BLE001 - evidence must never abort
        return '<error %s>' % type(error).__name__


def git_state(cwd=REPO) -> dict:
    lines = [x for x in git(['status', '--porcelain'], cwd).splitlines() if x.strip()]
    return {'head': git(['log', '-1', '--format=%H|%ad|%s', '--date=iso'], cwd),
            'branch': git(['branch', '--show-current'], cwd),
            'dirty_count': len(lines),
            'untracked_count': len([x for x in lines if x.startswith('??')])}


def lab_jobs() -> dict:
    if not LAB_DB.exists():
        return {'present': False}
    con = sqlite3.connect('file:%s?mode=ro' % str(LAB_DB).replace('\\', '/'), uri=True)
    try:
        cur = con.cursor()
        states = dict(cur.execute('select state, count(*) from jobs group by state'))
        profiles = cur.execute('select count(*) from profiles').fetchone()[0]
        active = [row[0] for row in cur.execute(
            'select id from jobs where state in (%s)' % ','.join('?' * len(ACTIVE_STATES)), ACTIVE_STATES)]
        deleted = cur.execute('select count(*) from jobs where deleted=1').fetchone()[0]
    finally:
        con.close()
    return {'present': True, 'size_bytes': LAB_DB.stat().st_size, 'sha256': sha256_file(LAB_DB),
            'jobs_by_state': states, 'profiles': profiles, 'deleted_jobs': deleted,
            'active_job_ids': active}


def packages() -> dict:
    def count(pattern: str, root: Path = DATA_DIR) -> int:
        return len(list(root.glob(pattern)))
    return {'problem_packages': count('lab_problem_packages/*.json'),
            'problem_package_attempts': count('lab_problem_packages/attempts/*.json'),
            'mysql_gates': count('lab_mysql_gates/*.json'),
            'mysql_gate_attempts': count('lab_mysql_gates/attempts/*.json'),
            'lab_corpus': count('lab_corpus/*.json'),
            'gate_files_recursive': count('**/*.gate.json')}


def published_corpus() -> dict:
    root = REPO / 'local/testcases'
    cases = sorted(root.glob('*/cases.json'))
    total = 0
    for path in cases:
        try:
            total += len(json.loads(path.read_text(encoding='utf-8')))
        except Exception:                                          # noqa: BLE001
            pass
    return {'problem_dirs': len(cases), 'total_cases': total}


def upstream_metrics() -> dict:
    """Reuse the maintained status-table calculator instead of re-deriving the 2x2."""
    try:
        from local.tools import gen_status_table as status
        return {'source': 'local.tools.gen_status_table',
                'metrics': status.metrics(), 'corpus': status.corpus_stats(),
                'golden': status.golden_stats(), 'fingerprint': status.fingerprint()}
    except Exception as error:                                     # noqa: BLE001
        return {'source': 'unavailable', 'error': '%s: %s' % (type(error).__name__, error)}


def consistency(closure: dict, image: str, metrics: dict) -> dict:
    if not PREV_BASELINE.exists():
        return {'previous': None}
    previous = json.loads(PREV_BASELINE.read_text(encoding='utf-8'))
    old_closure = previous.get('judge_closure') or {}
    changed = sorted(set(old_closure) ^ set(closure)) + sorted(
        path for path in set(old_closure) & set(closure) if old_closure[path] != closure[path])
    report = {'previous_baseline': str(PREV_BASELINE.relative_to(REPO)),
              'judge_closure_files_old': len(old_closure), 'judge_closure_files_now': len(closure),
              'judge_closure_changed': changed,
              'image_old': previous.get('image'), 'image_now': image,
              'image_unchanged': previous.get('image') == image}
    old_metrics = previous.get('historical_metrics') or {}
    for key in ('comparable_slots', 'tp', 'fn', 'fp', 'tn', 'false_ac', 'false_wa'):
        if key in old_metrics:
            now_value = metric(metrics, key)
            report['historical_%s' % key] = {'old': old_metrics[key], 'now': now_value,
                                             'unchanged': old_metrics[key] == now_value}
    return report


# gen_status_table.metrics() reports the 2x2 in SQL casing (N/TP/FN/FP/TN); the
# frozen baseline stores lower case. Read both instead of reporting a false diff.
ALIASES = {'comparable_slots': ('comparable_slots', 'N'), 'tp': ('tp', 'TP'), 'fn': ('fn', 'FN'),
           'fp': ('fp', 'FP'), 'tn': ('tn', 'TN'), 'false_ac': ('false_ac', 'FP'),
           'false_wa': ('false_wa', 'FN')}


def metric(metrics, key):
    for name in ALIASES.get(key, (key,)):
        if isinstance(metrics, dict) and name in metrics:
            return metrics[name]
    return None


def backup(evidence: Path) -> dict:
    """Consistent copy: the sqlite3 backup API folds in WAL, a plain file copy would not."""
    if not LAB_DB.exists():
        return {'present': False}
    target = evidence / 'backup'
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination = target / ('lab-%s.sqlite3' % stamp)
    source = sqlite3.connect('file:%s?mode=ro' % str(LAB_DB).replace('\\', '/'), uri=True)
    copy = sqlite3.connect(str(destination))
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    verify = sqlite3.connect('file:%s?mode=ro' % str(destination).replace('\\', '/'), uri=True)
    try:
        jobs = verify.execute('select count(*) from jobs').fetchone()[0]
        check = verify.execute('pragma integrity_check').fetchone()[0]
    finally:
        verify.close()
    manifest = SERVER_DIR / 'build-manifest.json'
    if manifest.exists():
        (target / ('build-manifest-%s.json' % stamp)).write_bytes(manifest.read_bytes())
    return {'backup': str(destination.relative_to(REPO)), 'bytes': destination.stat().st_size,
            'jobs': jobs, 'integrity_check': check, 'source_sha256': sha256_file(LAB_DB)}


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    closure = dict(judge_source_closure())
    image = image_digest()
    upstream = upstream_metrics()
    metrics = upstream.get('metrics') or {}
    manifest = SERVER_DIR / 'build-manifest.json'
    binary = SERVER_DIR / 'local-dashboard-server.exe'
    evidence = {
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'purpose': 'read-only baseline for the 2026-10-18 system handoff',
        'service': {'build_id': (json.loads(manifest.read_text(encoding='utf-8')).get('build_id')
                                 if manifest.exists() else None),
                    'binary': str(binary.relative_to(REPO)),
                    'binary_bytes': binary.stat().st_size if binary.exists() else None,
                    'web_dist_index': (REPO / 'local/dashboard/packages/web/dist/index.html').exists()},
        'source': {'repo': git_state(), 'local_repo': git_state(REPO / 'local')},
        'judge_closure': {'count': len(closure), 'files': closure},
        'image': image,
        'historical_metrics': metrics,
        'upstream': {k: v for k, v in upstream.items() if k != 'metrics'},
        'lab_jobs': lab_jobs(),
        'packages': packages(),
        'published_corpus': published_corpus(),
        'consistency': consistency(closure, image, metrics),
        'backup': backup(EVIDENCE),
    }
    target = EVIDENCE / 'baseline.json'
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=1, sort_keys=False), encoding='utf-8')

    q = chr(96)
    lines = ['# 本轮基线（2026-10-18）', '',
             '只读采集；不含凭据。SQLite 使用 backup API 一致性复制（含 WAL）。', '',
             '| 项 | 值 |', '|---|---|',
             '| 采集时间 (UTC) | %s |' % evidence['captured_at'],
             '| 服务构建 | %s%s%s |' % (q, (evidence['service']['build_id'] or 'None')[:16], q),
             '| 镜像 | %s%s%s |' % (q, image[:23], q),
             '| 正式判题器闭包 | %d 个文件 |' % len(closure),
             '| 根仓库 HEAD | %s%s%s |' % (q, evidence['source']['repo']['head'].split('|')[0][:12], q),
             '| 根仓库脏文件 | %d（未跟踪 %d） |' % (evidence['source']['repo']['dirty_count'], evidence['source']['repo']['untracked_count']),
             '| local 仓库 HEAD | %s%s%s |' % (q, evidence['source']['local_repo']['head'].split('|')[0][:12], q),
             '| local 仓库脏文件 | %d（未跟踪 %d） |' % (evidence['source']['local_repo']['dirty_count'], evidence['source']['local_repo']['untracked_count']),
             '| 可比槽位 | %s |' % metric(metrics, 'comparable_slots'),
             '| FP / FN | %s / %s |' % (metric(metrics, 'fp'), metric(metrics, 'fn')),
             '| lab 任务 | %s |' % json.dumps(evidence['lab_jobs'].get('jobs_by_state'), ensure_ascii=False),
             '| 活动任务 | %s |' % (evidence['lab_jobs'].get('active_job_ids') or '无'),
             '| 题包 / MySQL 门禁 | %s / %s |' % (evidence['packages']['problem_packages'], evidence['packages']['mysql_gates']),
             '| 已发布语料 | %s 题 / %s 用例 |' % (evidence['published_corpus']['problem_dirs'], evidence['published_corpus']['total_cases']),
             '| 一致性备份 | %s（%s 任务，integrity=%s） |' % (
                 evidence['backup'].get('backup'), evidence['backup'].get('jobs'), evidence['backup'].get('integrity_check')),
             '', '## 与 2026-10-15 基线的一致性', '']
    con = evidence['consistency']
    lines += ['- 闭包文件数：old %s → now %s' % (con.get('judge_closure_files_old'), con.get('judge_closure_files_now')),
              '- 闭包变化：%s' % (con.get('judge_closure_changed') or '无'),
              '- 镜像未变：%s' % con.get('image_unchanged')]
    for key in ('historical_comparable_slots', 'historical_fp', 'historical_fn', 'historical_tp', 'historical_tn'):
        if key in con:
            lines.append('- %s：old %s / now %s（一致 %s）' % (
                key.replace('historical_', ''), con[key]['old'], con[key]['now'], con[key]['unchanged']))
    (EVIDENCE / 'baseline.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('baseline ->', target)
    print('summary  ->', EVIDENCE / 'baseline.md')
    print('closure files:', len(closure), '| image:', image[:23])
    print('dirty:', evidence['source']['repo']['dirty_count'], evidence['source']['local_repo']['dirty_count'])
    print('jobs:', evidence['lab_jobs'].get('jobs_by_state'), '| active:', evidence['lab_jobs'].get('active_job_ids'))
    print('backup:', evidence['backup'].get('backup'), 'integrity=', evidence['backup'].get('integrity_check'))
    print('consistency:', json.dumps({k: v for k, v in con.items() if 'historical' not in k}, ensure_ascii=False)[:400])


if __name__ == '__main__':
    main()
