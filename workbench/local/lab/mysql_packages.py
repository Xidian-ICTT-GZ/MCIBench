"""Additional native-dialect reference gate for existing independent SQL corpora."""
from copy import deepcopy
import json
from pathlib import Path

from local.common import REPO_ROOT
from local.lab import mysql_runtime,problem_packages as packages,portable_judging as judging
from local.lab.behavior import sha
from local.lab.testcase_workflow import save,lock
from local.lab import source_guard

source_guard.register(__file__)
DATA_DIR=REPO_ROOT/'local/dashboard/packages/server/data/lab_mysql_gates'


def binding(qid,descriptor,package):
    result={'qid':qid,'runtime':mysql_runtime.identity(),'descriptor_sha256':sha(descriptor),
            'cases_sha256':sha(package['cases']),'package_sha256':package.get('package_sha256'),
            'gate_builder_sha256':sha(Path(__file__).read_text(encoding='utf8')),
            'checker_sha256':sha(Path(judging.__file__).read_text(encoding='utf8'))}
    if qid==1484:result['reference_contract']={'version':'portable-literal-product-collation-v1',
        'collation':'utf8mb4_0900_bin','scope':'matches_existing_case_sensitive_portable_contract',
        'leetcode_collation_equivalence':'not_established'}
    if qid==1873:result['reference_contract']={'version':'portable-literal-uppercase-prefix-v1',
        'collation':'utf8mb4_0900_bin','scope':'literal_uppercase_M_case_sensitive_bonus_condition',
        'leetcode_collation_equivalence':'not_established'}
    return result


def reviewed_reference(qid):
    if qid==1484:
        return "SELECT sell_date,COUNT(DISTINCT product COLLATE utf8mb4_0900_bin) AS num_sold,GROUP_CONCAT(DISTINCT product COLLATE utf8mb4_0900_bin ORDER BY product COLLATE utf8mb4_0900_bin SEPARATOR ',') AS products FROM Activities GROUP BY sell_date ORDER BY sell_date"
    return None


def completed_gate(verdict,count):
    return (verdict.get('state')=='SUCCESS' and verdict.get('ac_status')=='Accepted'
            and verdict.get('total_testcases')==count and verdict.get('total_correct')==count)


def prepare(qid,descriptor,package,profile,*,check_cancel=lambda:None,on_event=lambda e:None,directory=None):
    source_guard.check()
    directory=Path(directory or DATA_DIR)
    current=binding(qid,descriptor,package)
    path=directory/f'{qid}.json'
    with lock(qid,directory):
        try:
            old=json.loads(path.read_text(encoding='utf8'));digest=old.pop('sha256')
            if (digest==sha(old) and old['binding']==current and old['verdict']['ac_status']=='Accepted'
                    and old['verdict']['total_correct']==len(package['cases'])
                    and sha(old['oracle']['code'])==old['oracle']['code_sha256']):
                old['sha256']=digest
                return old
        except (OSError,ValueError,TypeError,KeyError):pass
        check_cancel();on_event({'qid':qid,'stage':'mysql_reference_gate','language':'mysql'})
        code=reviewed_reference(qid)
        if code:
            public=judging.execute(qid,'mysql',code,descriptor['official'],descriptor['comparison'],check_cancel=check_cancel)
            oracle={'language':'mysql','code':code,'code_sha256':sha(code),'origin':'reviewed_native_reference',
                    'reference_contract':current.get('reference_contract'),'official_gate':public}
            save(directory/'attempts'/f'{qid}-mysql-reviewed-oracle.json',oracle)
            if not completed_gate(public,len(descriptor['official'])):raise ValueError('经审查原生参考未完整通过公开示例，禁止模型自动修补或发布')
        else:
            oracle=packages._oracle(qid,'mysql',descriptor,profile,directory/'attempts'/f'{qid}-mysql-oracle.json',
                                    check_cancel,lambda record:None)
        verdict=judging.execute(qid,'mysql',oracle['code'],package['cases'],descriptor['comparison'],check_cancel=check_cancel)
        record={'binding':current,'oracle':oracle,'verdict':verdict}
        save(directory/'attempts'/f'{qid}-full-gate.json',record)
        if not completed_gate(verdict,len(package['cases'])):raise ValueError('原生 MySQL 参考程序未通过完整独立语料，候选保留但不签发判定')
        check_cancel()
        if current!=binding(qid,descriptor,package):raise ValueError('MySQL 配置在门禁期间变化，未发布')
        record['sha256']=sha(record);save(path,record)
        return record


def summary(record):
    return {'dialect':'mysql','environment':deepcopy(record['binding']['runtime']),
            'reference_source_sha256':record['oracle']['code_sha256'],'gate_sha256':record['sha256'],
            'reference_gate_status':record['verdict']['ac_status'],'reference_case_count':record['verdict']['total_testcases'],
            'cases_sha256':record['binding']['cases_sha256'],'limitations':record['binding']['runtime']['limits'],
            'reference_contract':deepcopy(record['binding'].get('reference_contract'))}
