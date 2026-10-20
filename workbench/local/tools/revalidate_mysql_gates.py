"""Re-execute signed native SQL references after lab runtime/profile changes."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.lab import mysql_packages as gates,problem_packages as packages,portable_judging as judging
from local.lab.behavior import sha
from local.lab.testcase_workflow import save,lock
from local.harness.identity import image_digest


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--qids',nargs='+',type=int,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    report={'scope':'retained_native_reference_source_and_unchanged_cases','checks':[]}
    image=image_digest()
    for qid in args.qids:
        with lock(qid,gates.DATA_DIR):
            path=gates.DATA_DIR/f'{qid}.json';old=json.loads(path.read_text(encoding='utf8'))
            signed=deepcopy(old);digest=signed.pop('sha256')
            if digest!=sha(signed) or old['verdict']['ac_status']!='Accepted':raise ValueError('Unsigned/incomplete prior MySQL reference gate')
            descriptor=packages.describe(qid);package=packages.read(qid,image,descriptor=descriptor)
            if not package:raise ValueError('Base package must pass current revalidation first')
            if sha(package['cases'])!=old['binding']['cases_sha256']:raise ValueError('Cases changed; explicit answer migration required')
            if sha(old['oracle']['code'])!=old['oracle']['code_sha256']:raise ValueError('Reference source drift')
            current=gates.binding(qid,descriptor,package)
            verdict=judging.execute(qid,'mysql',old['oracle']['code'],package['cases'],package['comparison'])
            check={'qid':qid,'previous_gate_sha256':digest,'source_sha256':old['oracle']['code_sha256'],
                   'verdict':verdict,'passed':verdict['ac_status']=='Accepted'}
            report['checks'].append(check);save(args.output,report)
            if not check['passed']:raise ValueError('Native reference failed; no gate published')
            if current!=gates.binding(qid,descriptor,package):raise ValueError('Runtime changed during native reference gate')
            save(gates.DATA_DIR/'archive'/str(qid)/(digest+'.json'),old)
            row={'binding':current,'oracle':old['oracle'],'verdict':verdict,
                 'revalidation':{'previous_gate_sha256':digest,'source_unchanged':True,'cases_unchanged':True}}
            row['sha256']=sha(row);save(path,row)
            print(qid,'NATIVE REFERENCE PASS',verdict['total_correct'],flush=True)
    print('Native references revalidated:',len(report['checks']))


if __name__=='__main__':main()
