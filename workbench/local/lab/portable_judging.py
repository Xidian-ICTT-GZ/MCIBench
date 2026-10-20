"""Trusted host checking for lab JSON functions, SQL tables and shell output."""
from copy import deepcopy
import json
import math
from decimal import Decimal
from pathlib import Path

from local.harness.output_protocol import PREFIX, OutputVerdict, _object, _nonfinite
from local.harness.runner import run_submission
from local.lab.behavior import sha
from local.lab import portable_drivers as drivers
from local.lab import result_semantics
from local.lab import source_guard
source_guard.register(__file__)

VERSION='full-corpus-json-v1'


def equal(got,expected,mode='ordered'):
    if type(expected) is bool:return type(got) is bool and got==expected
    if expected is None:return got is None
    if type(expected) is int:return type(got) is int and got==expected
    if type(expected) is float:
        return type(got) in (int,float,Decimal) and math.isfinite(float(got)) and abs(float(got)-expected)<1e-6
    if type(expected) is str:return type(got) is str and got==expected
    if type(expected) is dict:
        return type(got) is dict and set(got)==set(expected) and all(equal(got[k],v) for k,v in expected.items())
    if type(expected) is list:
        if type(got) is not list or len(got)!=len(expected):return False
        if mode in ('unordered','rows_unordered','all_unordered'):
            remaining=list(got)
            for item in expected:
                for i,other in enumerate(remaining):
                    if equal(other,item,'unordered' if mode=='all_unordered' else 'ordered'):
                        remaining.pop(i);break
                else:return False
            return True
        return all(equal(a,b) for a,b in zip(got,expected))
    return False


def compare(qid,got,case,comparison):
    expected=case['expected'];mode=comparison.get('mode','ordered')
    validity=result_semantics.valid(qid,got,case['args'])
    if validity is not None:return validity
    mode=result_semantics.mode(qid,mode)
    if qid==1:
        args=case['args'];nums=args['nums']
        return (type(got) is list and len(got)==2 and all(type(i) is int and 0<=i<len(nums) for i in got)
                and got[0]!=got[1] and nums[got[0]]+nums[got[1]]==args['target'])
    if mode=='table':
        keys={'columns','rows','types'} if comparison.get('require_types') else {'columns','rows'}
        if type(got) is not dict or set(got)!=keys or type(got['columns']) is not list:return False
        if comparison.get('require_types') and got['types']!=expected['types']:return False
        cols=expected['columns']
        scalar_heading=qid==177 and comparison.get('scalar_function_return') is True
        if any(type(c) is not str for c in got['columns']):return False
        if scalar_heading:
            if len(cols)!=1 or len(got['columns'])!=1 or len(expected['rows'])!=1:return False
        elif [c.casefold() for c in got['columns']]!=[c.casefold() for c in cols]:return False
        def cell_equal(a,b):
            # SQL/JSON tables do not distinguish 4 and 4.0, but bools and
            # numeric strings remain distinct. Never round large integers.
            if type(b) is int and type(a) is float:return math.isfinite(a) and Decimal(str(a))==Decimal(b)
            return equal(a,b)
        def row_equal(a,b):return type(a) is list and type(b) is list and len(a)==len(b) and all(cell_equal(x,y) for x,y in zip(a,b))
        rows=got['rows']
        if type(rows) is not list or len(rows)!=len(expected['rows']):return False
        if comparison.get('unordered_rows'):
            remaining=list(rows)
            for row in expected['rows']:
                for i,other in enumerate(remaining):
                    if row_equal(other,row):remaining.pop(i);break
                else:return False
            return True
        return all(row_equal(a,b) for a,b in zip(rows,expected['rows']))
    if mode=='shell_lines':
        if type(got) is not str:return False
        return [s.split() for s in got.rstrip('\n').splitlines()]==[s.split() for s in expected.rstrip('\n').splitlines()]
    if mode=='word_frequency':
        if type(got) is not str:return False
        from collections import Counter
        wanted=Counter(case['args']['files']['words.txt'].split())
        try:rows=[(line.split()[0],int(line.split()[1])) for line in got.splitlines() if line.strip()]
        except (ValueError,IndexError):return False
        return (len(rows)==len(wanted) and len({w for w,n in rows})==len(rows)
                and dict(rows)==dict(wanted) and [n for w,n in rows]==sorted(wanted.values(),reverse=True))
    return equal(got,expected,mode)


class JSONVerifier:
    def __init__(self,qid,cases,comparison=None,*,collect=False):
        self.qid,self.cases,self.comparison=qid,deepcopy(cases),comparison or {'mode':'ordered'}
        self.collect=collect;self.outputs=[];self.completed=0;self.terminal=None
        if not cases:raise ValueError('empty local judging corpus')

    def feed(self,line):
        if self.terminal or not line.startswith(PREFIX):return self.terminal
        try:
            row=json.loads(line[len(PREFIX):],object_pairs_hook=_object,parse_constant=_nonfinite)
            if (type(row) is not dict or set(row)!={'case','op','value'} or type(row['case']) is not int
                    or type(row['op']) is not int or row['case']!=self.completed or row['op']!=0 or self.completed>=len(self.cases)):
                raise ValueError('missing, duplicate, extra or out-of-order output')
            # Enforce finite values and a bounded, strict JSON serialization.
            if len(json.dumps(row['value'],allow_nan=False))>16*1024*1024:raise ValueError('output too large')
            if not self.collect and not compare(self.qid,row['value'],self.cases[self.completed],self.comparison):
                self.terminal=OutputVerdict('Wrong Answer',self.completed,self.completed,'host JSON comparison failed')
                return self.terminal
            self.outputs.append(row['value']);self.completed+=1
        except (TypeError,ValueError,RecursionError,OverflowError) as error:
            self.terminal=OutputVerdict('Runtime Error',self.completed,detail=str(error))
        return self.terminal

    def finish(self,exit_code,*,execution_failure=None):
        if self.terminal:return self.terminal
        if execution_failure:return OutputVerdict(execution_failure,self.completed)
        if exit_code!=0 or self.completed!=len(self.cases):return OutputVerdict('Runtime Error',self.completed,detail='incomplete JSON execution')
        return OutputVerdict('Collected' if self.collect else 'Accepted',self.completed)


def sql_driver(code,inputs,comparison):
    operation=comparison.get('mutation_operation','delete')
    if operation not in ('delete','update'):raise ValueError('unsupported SQL mutation operation')
    constants='SQL='+repr(code)+'\nMUTATION='+repr(bool(comparison.get('mutation')))+'\nRESULT_TABLE='+repr(comparison.get('result_table',''))+'\nMUTATION_OPERATION='+repr(operation)+'\n'
    return constants+'''import sqlite3,json,math,re,datetime
def _quote(s):
 return '"'+s.replace('"','""')+'"'
def solve(data):
 db=sqlite3.connect(':memory:')
 db.create_function('CONCAT',-1,lambda *a: ''.join(str(v) for v in a) if all(v is not None for v in a) else None)
 db.create_function('DATEDIFF',2,lambda a,b:(datetime.date.fromisoformat(a[:10])-datetime.date.fromisoformat(b[:10])).days if a and b else None)
 db.create_function('YEAR',1,lambda s:int(s[:4]) if s else None)
 db.create_function('MONTH',1,lambda s:int(s[5:7]) if s else None)
 db.create_function('DAY',1,lambda s:int(s[8:10]) if s else None)
 db.create_function('REGEXP',2,lambda p,s:bool(re.search(p,s)) if s is not None else False)
 db.create_function('MOD',2,lambda a,b:a%b if a is not None and b else None)
 for name,table in data['tables'].items():
  columns=table['columns'];types=table.get('types',[])
  defs=[_quote(c)+' '+(types[i] if i<len(types) and types[i] in ('INTEGER','REAL','TEXT') else 'TEXT') for i,c in enumerate(columns)]
  db.execute('CREATE TABLE '+_quote(name)+' ('+','.join(defs)+')')
  db.executemany('INSERT INTO '+_quote(name)+' VALUES ('+','.join('?' for _ in columns)+')',table['rows'])
 query=SQL
 params={k:v for k,v in data.items() if k!='tables'}
 writes=[]
 def authorize(action,table,column,database,trigger):
  if action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
   expected=sqlite3.SQLITE_DELETE if MUTATION_OPERATION=='delete' else sqlite3.SQLITE_UPDATE
   if not MUTATION or action!=expected or table.casefold()!=RESULT_TABLE.casefold():return sqlite3.SQLITE_DENY
   writes.append(table)
  return sqlite3.SQLITE_OK
 db.set_authorizer(authorize)
 cursor=db.execute(query,params)
 if MUTATION:
  if not writes:raise ValueError('a '+MUTATION_OPERATION.upper()+' mutation statement is required')
  if cursor.description is not None:cursor.fetchall()
  cursor=db.execute('SELECT * FROM '+_quote(RESULT_TABLE))
 elif cursor.description is None:raise ValueError('query produced no result table')
 out={'columns':[c[0] for c in cursor.description],'rows':[list(r) for r in cursor.fetchall()]}
 db.close()
 return out
''' + _python_loop(inputs)


def shell_driver(code,inputs,*,filter_no_match=False):
    return '''import json,subprocess,tempfile,pathlib,re
def solve(data):
 with tempfile.TemporaryDirectory(dir='/w') as directory:
  for name,value in data['files'].items():
   if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',name) or name in ('.','..'):raise ValueError('invalid filename')
   pathlib.Path(directory,name).write_text(value,encoding='utf8')
  result=subprocess.run(['bash','-c',SCRIPT],cwd=directory,capture_output=True,text=True,timeout=5)
  # grep's documented status 1 means no matches, a valid empty filter result.
  no_match=ALLOW_NO_MATCH and result.returncode==1 and not result.stdout and not result.stderr
  if result.returncode and not no_match:raise RuntimeError(result.stderr[:1000] or ('script exit '+str(result.returncode)))
  return result.stdout.rstrip('\\n')
''' .replace('ALLOW_NO_MATCH',str(bool(filter_no_match))).replace("['bash','-c',SCRIPT]","['bash','-c',"+repr(code)+']')+_python_loop(inputs)


def _python_loop(inputs):
    return '\n_inputs=json.loads('+repr(json.dumps(inputs,ensure_ascii=True))+')\nfor i,data in enumerate(_inputs):\n print("MCIBENCH_OUTPUT_V1 "+json.dumps({"case":i,"op":0,"value":solve(data)},allow_nan=False),flush=True)\n'


def _mysql(qid,code,cases,comparison,*,collect,check_cancel):
    from local.lab import mysql_runtime,problem_io
    official,_,_=problem_io.official(qid)
    if problem_io.kind(qid)!='database' or not official:raise ValueError('MySQL requires a verified database problem contract')
    for case in cases:
        problem_io.input_valid_shape(case['args'])
        problem_io.check_database_input(qid,case['args'],official[0]['args'])
    effective={**comparison,'dialect':'mysql'}
    verifier=JSONVerifier(qid,cases,effective,collect=collect)
    error=''
    with mysql_runtime.Session(qid,check_cancel=check_cancel) as session:
        for i,case in enumerate(cases):
            check_cancel()
            try:output=session.run_case(code,deepcopy(case['args']),effective,i)
            except mysql_runtime.SQLFailure as failure:
                error=str(failure)
                verifier.terminal=OutputVerdict(failure.status,verifier.completed,detail=error)
                break
            terminal=verifier.feed(PREFIX+json.dumps({'case':i,'op':0,'value':output},allow_nan=False))
            if terminal:break
        terminal=verifier.finish(0)
        check_cancel()
        meta={'runtime_language':'mysql','execution_environment':session.environment,
              'driver_version':mysql_runtime.VERSION,'driver_sha256':sha(code),
              'comparison':effective,'error':error or getattr(terminal,'detail',''),
              'asan_required':False,'column_metadata':session.columns,'input_schemas':session.schemas,
              'query_runtime_ms':session.runtime_ms,'expected_answers_entered_database':False}
        return {'state':'SUCCESS','ac_status':terminal.status,'total_testcases':len(cases),
                'total_correct':verifier.completed,'runtime':f'{session.runtime_ms:.0f} ms','memory':'',
                'version':'full-corpus-mysql-v1','cases_sha256':sha(cases),'correctness_order':'frozen_corpus_order',
                '_meta':meta,'outputs':verifier.outputs if collect else []}


def execute(qid,language,code,cases,comparison=None,*,collect=False,check_cancel=lambda:None,native_bridge=False):
    source_guard.check()
    inputs=[deepcopy(c['args']) for c in cases]
    comparison=comparison or {'mode':'ordered'}
    check_cancel()
    if language=='mysql':return _mysql(qid,code,cases,comparison,collect=collect,check_cancel=check_cancel)
    runtime_language=language
    if language=='sqlite':driver=sql_driver(code,inputs,comparison);runtime_language='python3'
    elif language=='bash':driver=shell_driver(code,inputs,filter_no_match=qid==193);runtime_language='python3'
    else:driver=drivers.render(language,code,inputs,native_bridge=native_bridge)
    if len(driver.encode())>16*1024*1024:raise ValueError('判题输入与驱动超过大小预算')
    verifier=JSONVerifier(qid,cases,comparison,collect=collect)
    result=run_submission(runtime_language,driver,limit=len(cases),backend='docker',run_timeout_s=5,
                          output_verifier=verifier)
    check_cancel()
    meta={'driver_version':drivers.VERSION,'driver_sha256':sha(driver),'asan_required':language in ('c','cpp'),
          'execution_supervisor':result.supervisor_protocol,'error':result.log[:2000],
          'comparison':comparison,'runtime_language':runtime_language}
    if not collect and result.status=='Accepted' and language in ('c','cpp'):
        check_cancel();asan_verifier=JSONVerifier(qid,cases,comparison)
        confirmation=run_submission(language,driver,limit=len(cases),backend='docker',run_timeout_s=5,
                                    asan=True,output_verifier=asan_verifier)
        check_cancel()
        meta['asan_status']='passed' if confirmation.status=='Accepted' else confirmation.status
        if confirmation.status!='Accepted':
            if confirmation.status=='Runtime Error' and 'AddressSanitizer' in confirmation.stderr:
                result=confirmation
                meta['error']=confirmation.log[:2000]
            else:raise ValueError('完整复判未完成 ASan 确认：'+confirmation.log[:300])
    elif language in ('c','cpp'):meta['asan_status']='not_required_for_collection' if collect else 'not_accepted'
    return {'state':'SUCCESS','ac_status':result.status,'total_testcases':len(cases),'total_correct':result.total_correct or 0,
            'runtime':f'{result.runtime_ms:.0f} ms' if result.runtime_available else '',
            'memory':f'{result.memory_mb:.1f} MB' if result.memory_available else '',
            'version':VERSION,'cases_sha256':sha(cases),'correctness_order':'frozen_corpus_order',
            '_meta':meta,'outputs':verifier.outputs if collect else []}
