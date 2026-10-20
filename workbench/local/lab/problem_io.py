"""Catalog-wide problem kinds and deterministic public-example normalization."""
from functools import lru_cache
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path

from local.common import DESCRIPTIONS_DIR, SNIPPETS_DIR, LANGS, KEY_TO_LABEL
from local.lab import source_guard
source_guard.register(__file__)
STATEMENT_REVISIONS=Path(__file__).with_name('data')/'statement_revisions.json'
source_guard.register(STATEMENT_REVISIONS)

LANGUAGES={**KEY_TO_LABEL,'mysql':'SQL (MySQL 8.0)','sqlite':'SQL (SQLite)','bash':'Bash'}
VERSION='problem-json-contract-v1'


@lru_cache(maxsize=4096)
def kind(qid):
    folder=SNIPPETS_DIR/str(qid)
    if (folder/'MySQL.json').is_file():return 'database'
    if (folder/'Pandas.json').is_file():return 'dataframe'
    if (folder/'Bash.json').is_file():return 'shell'
    return 'algorithm'


def languages(qid):
    return list(LANGS)+(['mysql','sqlite'] if kind(qid)=='database' else ['bash'] if kind(qid)=='shell' else [])


def description(qid):
    folder=DESCRIPTIONS_DIR/str(qid)
    files=sorted(folder.glob('*English*.txt')) or sorted(folder.glob('*.txt'))
    if not files:raise ValueError(f'q{qid} 缺少题面')
    text=files[0].read_text(encoding='utf-8')
    revision=statement_revision(qid,base=text)
    return text.replace(revision['old_excerpt'],revision['new_excerpt']) if revision else text


def statement_revision(qid,*,base=None):
    if qid not in (3374,3451):return None
    source_guard.check()
    record=json.loads(STATEMENT_REVISIONS.read_text(encoding='utf8'))
    if record.get('version')!=1:raise ValueError('statement revision evidence version changed; review required')
    revision=record['problems'][str(qid)]
    if base is None:
        folder=DESCRIPTIONS_DIR/str(qid)
        files=sorted(folder.glob('*English*.txt')) or sorted(folder.glob('*.txt'))
        base=files[0].read_text(encoding='utf8')
    if (revision['base_description_sha256']!=hashlib.sha256(base.encode('utf8')).hexdigest()
            or base.count(revision['old_excerpt'])!=1 or revision['source']['questionFrontendId']!=str(qid)):
        raise ValueError('local statement differs from the reviewed revision baseline; explicit review required')
    return deepcopy(revision)


def main_statement(qid):
    return re.split(r'(?im)^\s*Follow[\s-]*up\s*[:：]',description(qid),maxsplit=1)[0].rstrip()


def parse_json(text):
    text=text.strip().replace('\u00a0',' ')
    from local.lab.public_literals import decode
    value,end=decode(text)
    return value,text[end:].strip()


def assignments(text):
    data={};remaining=text.strip()
    while remaining:
        match=re.match(r'(\w+)\s*=\s*',remaining)
        if not match:raise ValueError('input assignment required')
        value,remaining=parse_json(remaining[match.end():])
        data[match[1]]=value
        if not remaining:break
        if remaining.startswith(','):remaining=remaining[1:].strip()
        elif not re.match(r'\w+\s*=',remaining):raise ValueError('unexpected input trailing data')
    return data


def table_value(value):
    if value.casefold()=='null':return None
    if re.fullmatch(r'-?\d+',value):return int(value)
    if re.fullmatch(r'-?\d+\.\d+',value):return float(value)
    return value


def table(text,types=None):
    rows=[]
    for line in text.splitlines():
        stripped=line.strip()
        if stripped.startswith('|') and stripped.endswith('|'):
            values=[v.strip() for v in stripped[1:-1].split('|')]
            if len(rows)==1 and all(re.fullmatch(r':?-{3,}:?',v) for v in values):continue
            rows.append(values)
        elif rows and stripped and not stripped.startswith('+'):break
    if not rows:raise ValueError('no SQL table')
    if any(len(r)!=len(rows[0]) for r in rows):raise ValueError('inconsistent SQL table widths')
    def cell(column,value):
        # Consult the declared schema before parsing numbers; TEXT "001"
        # must not be irreversibly reduced to integer 1.
        if value.casefold()=='null':return None
        return value if types and types.get(column)=='TEXT' else table_value(value)
    return {'columns':rows[0],'rows':[[cell(c,v) for c,v in zip(rows[0],r)] for r in rows[1:]]}


def dataframe_input(qid,text):
    """Match displayed tables to the declared Pandas parameter names."""
    import ast
    snippet=json.loads((SNIPPETS_DIR/str(qid)/'Pandas.json').read_text(encoding='utf8'))
    method=next(n for n in ast.parse(snippet.rstrip()+'\n    pass\n').body if isinstance(n,ast.FunctionDef))
    names=[p.arg for p in method.args.args]
    groups=re.findall(r'(?m)(?:^\s*\+[^\n]+\n)?(?:^\s*\|[^\n]*\n|^\s*\+[^\n]*\n)+',text)
    tables=[table(group) for group in groups if '|' in group]
    if len(tables)!=len(names):raise ValueError('dataframe parameter/table count mismatch')
    result={}
    for name,data in zip(names,tables):
        data['rows']=[[None if v in ('None','NaN','nan','<NA>') else v for v in row] for row in data['rows']]
        data['types']=['INTEGER' if all(v is None or type(v) is int for v in col) else 'REAL' if all(v is None or type(v) in (int,float) for v in col) else 'TEXT' for col in zip(*data['rows'])]
        if not data['rows']:data['types']=['TEXT']*len(data['columns'])
        result[name]=data
    return result


def sql_schemas(text):
    schemas={}
    for m in re.finditer(r'(?:Table|SQL Schema)\s*:\s*([A-Za-z_]\w*)\s*\n',text,re.I):
        try:
            data=table(text[m.end():]);schemas[m[1]]={str(r[0]):('INTEGER' if str(r[1]).lower() in ('int','integer','bigint','boolean')
                    else 'REAL' if any(t in str(r[1]).lower() for t in ('decimal','float','double')) else 'TEXT') for r in data['rows']}
        except (ValueError,IndexError):continue
    return schemas


def sql_primary_keys(qid):
    """Extract only explicit primary-key declarations with table-local scope."""
    text=description(qid).split('Example',1)[0]
    sections=list(re.finditer(r'(?:Table|SQL Schema)\s*:\s*([A-Za-z_]\w*)\s*\n',text,re.I))
    keys=[]
    for i,section in enumerate(sections):
        body=text[section.end():sections[i+1].start() if i+1<len(sections) else len(text)]
        for match in re.finditer(r'(\([A-Za-z_\w, ]+\)|[A-Za-z_]\w*)\s+is\s+(?:the\s+)?primary\s+key',body,re.I):
            keys.append({'table':section[1],'columns':[v.strip() for v in match[1].strip('()').split(',')],'excerpt':match[0]})
    return keys


def check_database_input(qid,args,template):
    """Schema/representation and explicit key checks, independent of model code."""
    import math
    if type(args.get('tables')) is not dict or set(args['tables'])!=set(template['tables']):raise ValueError('input database table names changed')
    for name,schema in template['tables'].items():
        value=args['tables'][name]
        if (type(value) is not dict or not {'columns','rows'}<=set(value)<={'columns','rows','types'} or value['columns']!=schema['columns']
                or type(value['rows']) is not list or 'types' in value and value['types']!=schema['types']):raise ValueError('input database schema changed')
        for row in value['rows']:
            if type(row) is not list or len(row)!=len(schema['columns']):raise ValueError('input database row shape changed')
            for cell,type_ in zip(row,schema['types']):
                if cell is None:continue
                valid=(type(cell) is int and -(2**63)<=cell<2**63 if type_=='INTEGER' else
                       type(cell) in (int,float) and math.isfinite(cell) and (type(cell) is not int or -(2**63)<=cell<2**63) if type_=='REAL' else type(cell) is str)
                if not valid:raise ValueError('input database cell type changed or exceeds runtime representation')
    for key in sql_primary_keys(qid):
        table_name=next((name for name in args['tables'] if name.casefold()==key['table'].casefold()),None)
        if table_name is None:raise ValueError('explicit primary-key table missing')
        table_=args['tables'][table_name];names=[c.casefold() for c in table_['columns']]
        if any(c.casefold() not in names for c in key['columns']):raise ValueError('explicit primary-key column missing')
        indices=[names.index(c.casefold()) for c in key['columns']];seen=set()
        for row in table_['rows']:
            values=tuple(row[j] for j in indices)
            if any(v is None for v in values) or values in seen:raise ValueError('explicit primary-key uniqueness/non-null constraint violated: '+key['excerpt'])
            seen.add(values)
    if qid==627:
        salary=args['tables']['Salary'];sex=salary['columns'].index('sex')
        if any(row[sex] not in ('m','f') for row in salary['rows']):raise ValueError('Salary.sex must be one of the declared ENUM values m/f')
    if qid==602:
        degrees=friend_degrees(args)
        if not degrees or sum(v==max(degrees.values()) for v in degrees.values())!=1:
            maximum=max(degrees.values(),default=0);leaders=[p for p,n in degrees.items() if n==maximum]
            raise ValueError('q602 main statement guarantees exactly one person with the most friends; tied/empty cases are excluded. max_degree='+str(maximum)+'; leaders='+str(leaders[:8]))
    if qid in (1693,1789,1934,3374,3436,3451):
        from local.lab import sql_answers
        if sql_answers.valid(qid,args) is not True:
            raise ValueError('reviewed SQL input rules rejected input: '+sql_answers.note(qid))
    return True


def friend_degrees(args):
    """Reviewed simple undirected friendship scope, with explicit exclusions."""
    table_=args['tables']['RequestAccepted'];columns=table_['columns']
    left,right=(columns.index(c) for c in ('requester_id','accepter_id'))
    graph={};edges=set()
    for row in table_['rows']:
        a,b=row[left],row[right];edge=tuple(sorted((a,b)))
        if a==b or edge in edges:raise ValueError('q602 self/repeated reverse friendship edges are outside the reviewed simple-graph scope; retained as unverified')
        edges.add(edge);graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
    return {k:len(v) for k,v in graph.items()}


def example_blocks(text):
    chunks=re.split(r'\bExample\s*\d*\s*:\s*',text,flags=re.I)
    return [re.split(r'\n\s*(?:Constraints|Follow-up|Note)\s*:',chunk,maxsplit=1,flags=re.I)[0] for chunk in chunks[1:]]


def reviewed_products_public(args,shown,statement):
    """Correct only the located q1484 T-Shirt example typo, with its old value."""
    from copy import deepcopy
    if shown.get('columns')!=['sell_date','num_sold','products']:raise ValueError('unverified q1484 public output shape')
    old=['2020-05-30',3,'Basketball,Headphone,T-shirt']
    if old not in shown.get('rows',[]):return deepcopy(shown),[]
    excerpt='The sold products names for each date should be sorted lexicographically.'
    products=args.get('tables',{}).get('Activities',{})
    if (excerpt not in statement or products.get('columns')!=['sell_date','product']
            or {r[1] for r in products.get('rows',[]) if r[0]=='2020-05-30'}!={'Basketball','Headphone','T-Shirt'}):
        raise ValueError('q1484 public spelling correction lacks its exact input/statement evidence')
    corrected=deepcopy(shown)
    corrected['rows'][corrected['rows'].index(old)]=['2020-05-30',3,'Basketball,Headphone,T-Shirt']
    return corrected,[{'rule':'concatenation_preserves_input_product_spelling','statement_excerpt':excerpt,
                       'original_expected':deepcopy(shown),'input_spelling':'T-Shirt',
                       'changed_cell':{'date':'2020-05-30','from':old[2],'to':corrected['rows'][shown['rows'].index(old)][2]}}]


def reviewed_daily_date_case(case,statement):
    """Normalize only q1693's explicitly declared DATE cells; retain old JSON."""
    from copy import deepcopy
    from local.lab.sql_answers import canonical_day,DATE_PROFILE
    declaration=re.search(r'\|\s*date_id\s*\|\s*date\s*\|',statement,re.I)
    if not declaration:raise ValueError('q1693 DATE codec lacks its exact type declaration')
    original=deepcopy(case);result=deepcopy(case);table_=result['args']['tables']['DailySales']
    position=table_['columns'].index('date_id')
    for row in table_['rows']:row[position]=canonical_day(row[position])
    output_position=result['expected']['columns'].index('date_id')
    for row in result['expected']['rows']:row[output_position]=canonical_day(row[output_position])
    if result!=original:
        result['normalization_evidence']=[{'rule':DATE_PROFILE,'statement_excerpt':declaration[0],
            'original_args':original['args'],'original_expected':original['expected'],
            'calendar_values_unchanged':True,'ordinary_TEXT_cells_unchanged':True}]
        result['origin']='official_example_reviewed_DATE_codec'
    return result


def official(qid):
    text=description(qid);cases=[];comparison={'mode':'ordered'};warnings=[]
    for old,new in (('示例','Example'),('输入','Input'),('输出','Output'),('解释','Explanation'),('提示','Constraints')):
        text=re.sub(r'(?m)^([ \t]*)'+old+r'(\s*\d*)[：:]',lambda m:m[1]+new+m[2]+':',text)
    text=re.sub(r'(Example\s*\d+)：',r'\1:',text)
    family=kind(qid)
    from local.lab import javascript_protocol,javascript_async
    if qid in javascript_protocol.QIDS|javascript_async.QIDS:
        from local.lab.public_literals import decode
        for block in example_blocks(text):
            m=re.search(r'Input\s*:?\s*(.*?)\bOutput\s*:?\s*(.*?)(?:\n\s*Explanation\s*:?|\Z)',block,re.S)
            if not m:continue
            try:
                args=(javascript_async.official_input(qid,m[1].strip(),block,decode,assignments) if qid in javascript_async.QIDS else javascript_protocol.official_input(qid,m[1].strip(),decode))
                expected,trailing=parse_json(m[2])
                if trailing:raise ValueError('unexpected callback output suffix')
                validator=javascript_async.valid if qid in javascript_async.QIDS else javascript_protocol.valid
                if validator(qid,args) is not True:raise ValueError('public callback protocol invalid')
                case={'args':args,'expected':expected,'origin':'official_example_reviewed_protocol',
                      'input_excerpt':m[1].strip(),'output_excerpt':m[2].strip()}
                if qid in (2715,2725):case['construction_evidence']={'cancelTimeMs':re.search(r'\bconst\s+cancelTimeMs\s*=\s*\d+\s*;',block)[0]}
                cases.append(case)
            except (ValueError,TypeError,KeyError,SyntaxError) as error:warnings.append(str(error))
        return cases,comparison,warnings
    if family=='shell':return shell_official(qid),{'mode':'word_frequency' if qid==192 else 'shell_lines'},[]
    if family=='database':
        schemas=sql_schemas(text)
        comparison={'mode':'table','unordered_rows':bool(re.search(r'(?:any order|\border\b[^.\n]{0,160}\bdoes not matter)',text,re.I)),
                    'dialect':'sqlite','mutation':qid in (196,627)}
        if qid==627:comparison.update(mutation_operation='update',unordered_rows=True)
        if qid==177:comparison['scalar_function_return']=True
        if qid==1211:
            from local.lab.sql_answers import NUMERIC_PROFILE
            comparison['numeric_profile']=NUMERIC_PROFILE
        if qid in (1633,1661):
            from local.lab import sql_answers
            comparison['numeric_profile']=sql_answers.PERCENT_PROFILE if qid==1633 else sql_answers.ACTIVITY_PROFILE
        if qid==1693:
            from local.lab.sql_answers import DATE_PROFILE
            comparison['date_profile']=DATE_PROFILE
        if qid in (1934,3374,3451):
            from local.lab.sql_review_batch8 import CONFIRM_PROFILE,WORD_PROFILE,IP_PROFILE
            if qid==1934:comparison['numeric_profile']=CONFIRM_PROFILE
            if qid==3374:comparison.update(text_case_profile=WORD_PROFILE,unordered_rows=True)
            if qid==3451:comparison['input_rule_profile']=IP_PROFILE
        output_types={}
        for schema in schemas.values():
            for column,type_ in schema.items():
                if column not in output_types:output_types[column]=type_
                elif output_types[column]!=type_:output_types[column]=None
        if qid==180:output_types['ConsecutiveNums']='TEXT'  # Copies Logs.num.
        for block in example_blocks(text):
            m=re.search(r'Input\s*:?\s*(.*?)\bOutput\s*:?\s*(.*?)(?:\n\s*Explanation\s*:?|\Z)',block,re.S)
            if not m:continue
            try:
                tables={}
                for tm in re.finditer(r'(?m)^([A-Za-z_]\w*)\s*(?:table)?\s*:?\s*\n(?=\s*\+)',m[1],re.I):
                    types=schemas.get(tm[1],{});data=table(m[1][tm.end():],types)
                    data['types']=[types.get(c,'INTEGER' if all(row[i] is None or type(row[i]) is int for row in data['rows']) else 'REAL' if all(row[i] is None or type(row[i]) in (int,float) for row in data['rows']) else 'TEXT') for i,c in enumerate(data['columns'])]
                    tables[tm[1]]=data
                if not tables:raise ValueError('no named input table')
                args={'tables':tables}
                for pm in re.finditer(r'\b([A-Za-z_]\w*)\s*=\s*(-?\d+)\b',m[1]):args[pm[1]]=int(pm[2])
                expected=table(m[2],output_types)
                if qid==177:expected['columns']=['getNthHighestSalary']
                case={'args':args,'expected':expected,'origin':'official_example'}
                if qid==1179 and '...' in expected['columns']:
                    from local.lab.sql_answers import expand_pivot_public
                    case['expected'],case['normalization_evidence']=expand_pivot_public(args,expected,text)
                    case['origin']='official_example_reviewed_ellipsis_expansion'
                if qid==1484:
                    case['expected'],evidence=reviewed_products_public(args,expected,text)
                    if evidence:
                        case['normalization_evidence']=evidence
                        case['origin']='official_example_reviewed_spelling_correction'
                if qid==1693:case=reviewed_daily_date_case(case,text)
                cases.append(case)
            except (ValueError,KeyError,IndexError) as error:warnings.append(str(error))
        if comparison['mutation'] and cases:comparison['result_table']=next(iter(cases[0]['args']['tables']))
        return cases,comparison,warnings
    for block in example_blocks(text):
        m=re.search(r'Input\s*:?\s*(.*?)\bOutput\s*:?\s*(.*?)(?:\n\s*(?:Explanation|Explaination|Explantion|Explanantion)\s*:?|\Z)',block,re.S)
        if not m:continue
        try:
            raw_input=m[1].strip();raw_output=m[2].strip()
            raw_output=re.sub(r'^(?:Output\s*:\s*)+','',raw_output)
            if family=='dataframe':
                # A list used to CREATE a dataframe remains a list. Only actual
                # tabular inputs require the columns/types/rows representation.
                named=re.match(r'(\w+)\s*:\s*(\[)',raw_input)
                if named:
                    value,remaining=parse_json(raw_input[named.start(2):])
                    if remaining:raise ValueError('ambiguous dataframe list input')
                    try:expected,trailing=parse_json(raw_output)
                    except ValueError:expected=table(raw_output);trailing=''
                    if trailing:raise ValueError('ambiguous dataframe output')
                    cases.append({'args':{named[1]:value},'expected':expected,'origin':'official_example'})
                    if type(expected) is dict and set(expected)=={'columns','rows'}:comparison={'mode':'table','unordered_rows':False}
                    continue
                values=dataframe_input(qid,raw_input)
                try:expected,trailing=parse_json(raw_output)
                except ValueError:expected=table(raw_output);trailing=''
                if trailing:raise ValueError('ambiguous dataframe output')
                if qid==2886:
                    expected['types']=['INTEGER' if all(v is None or type(v) is int for v in col) else 'REAL' if all(v is None or type(v) in (int,float) for v in col) else 'TEXT' for col in zip(*expected['rows'])]
                cases.append({'args':values,'expected':expected,'origin':'official_example_reviewed_serialization'})
                if type(expected) is dict and {'columns','rows'}<=set(expected):comparison={'mode':'table','unordered_rows':False,'require_types':qid==2886}
                continue
            if qid==1410:
                repaired=re.fullmatch(r'text\s*=\s*"(.*)"',raw_input,re.S)
                if not repaired:raise ValueError('unrecognized quoted HTML example')
                values={'text':repaired[1]}
            elif raw_input.startswith('['):
                ops,remaining=parse_json(raw_input);args,tail=parse_json(remaining)
                if tail:raise ValueError('unexpected design trace suffix')
                if type(ops) is not list or not ops or not all(type(o) is str for o in ops) or len(ops)!=len(args):raise ValueError('invalid design trace')
                values={'ops':ops,'args':args}
            else:
                try:values=assignments(raw_input)
                except ValueError:
                    from local.common import load_snippet
                    import ast
                    signature=ast.parse(load_snippet(qid,'python3')+'\n        pass\n')
                    method=next(n for n in ast.walk(signature) if isinstance(n,ast.FunctionDef) and n.name!='__init__')
                    params=[a.arg for a in method.args.args if a.arg!='self']
                    value,remaining=parse_json(raw_input)
                    if len(params)!=1 or remaining:raise ValueError('ambiguous unnamed input')
                    values={params[0]:value}
            if qid in (116,117):
                expected,trailing=parse_json(re.sub(r'(?<![\w"\'])#(?![\w"\'])','"#"',raw_output))
            elif qid==142:
                match=re.fullmatch(r'tail connects to node index (\d+)',raw_output)
                if match:expected={'node_index':int(match[1])}
                elif raw_output.casefold()=='no cycle':expected={'node_index':None}
                else:raise ValueError('unrecognized cycle identity output')
                trailing=''
            elif qid==160:
                match=re.fullmatch(r"Intersected at ['\"](\d+)['\"]",raw_output)
                if match:
                    if int(match[1])!=values['intersectVal']:raise ValueError('intersection value disagrees with input')
                    expected={'a_index':values['skipA'],'b_index':values['skipB']}
                elif raw_output.casefold()=='no intersection':expected=None
                else:raise ValueError('unrecognized intersection identity output')
                trailing=''
            elif qid==843:
                if raw_output!='You guessed the secret word correctly.':raise ValueError('unrecognized Master success output')
                expected={'guessed':True};trailing=''
            elif qid==443:
                mutation=re.match(r'Return\s+(\d+).*?:\s*(\[[^\n]*\])',raw_output,re.S)
                if not mutation:raise ValueError('invalid compression example')
                expected={'return':int(mutation[1]),'mutated':{'chars':json.loads(mutation[2])}};trailing=''
            else:expected,trailing=parse_json(raw_output)
            if trailing.startswith(','):
                # In-place prefix contracts expose exactly the required prefix.
                mutation=re.match(r',\s*(\w+)\s*=\s*(\[[^\n]*\])',trailing)
                if not mutation:raise ValueError('unsupported mutation output')
                value=json.loads(re.sub(r'(?<![\w"])_(?![\w"])','null',mutation[2]))
                if type(expected) is not int:raise ValueError('mutation prefix length required')
                expected={'return':expected,'mutated':{mutation[1]:value[:expected]}}
            elif (qid==2659 and re.match(r'Operation\s+Array\b',trailing)) or (qid==1998 and trailing.startswith('We can sort ')):pass
            elif trailing and not trailing.startswith(('\n','Explanation','The ','Note:')):
                # Never silently use a parsed prefix of a different output contract.
                raise ValueError('ambiguous official output suffix')
            cases.append({'args':values,'expected':expected,'origin':'official_example'})
        except (ValueError,TypeError,KeyError,OSError,SyntaxError,StopIteration) as error:warnings.append(str(error))
    # Ordering hints are used only where the statement explicitly permits them.
    if re.search(r'(?:return|answer|result)[^\n.]{0,100}(?:in any order|order does not matter)',text,re.I):
        comparison['mode']='rows_unordered' if cases and type(cases[0]['expected']) is list and cases[0]['expected'] and type(cases[0]['expected'][0]) is list else 'unordered'
    return cases,comparison,warnings


def shell_official(qid):
    rows={192:({'files':{'words.txt':'the day is sunny the the\nthe sunny is is\n'}},'the 4\nis 3\nsunny 2\nday 1'),
          193:({'files':{'file.txt':'987-123-4567\n123 456 7890\n(123) 456-7890\n'}},'987-123-4567\n(123) 456-7890'),
          194:({'files':{'file.txt':'name age\nalice 21\nryan 30\n'}},'name alice ryan\nage 21 30'),
          195:({'files':{'file.txt':'\n'.join(f'Line {i}' for i in range(1,11))+'\n'}},'Line 10')}
    if qid not in rows:return []
    args,expected=rows[qid]
    return [{'args':args,'expected':expected,'origin':'official_example_reviewed_serialization'}]


def shell_answer(qid,args):
    from collections import Counter
    files=args['files'];text=files['words.txt' if qid==192 else 'file.txt']
    if qid==192:return '\n'.join(f'{w} {n}' for w,n in sorted(Counter(text.split()).items(),key=lambda p:(-p[1],p[0])))
    if qid==193:return '\n'.join(s for s in text.splitlines() if re.fullmatch(r'(?:\d{3}-\d{3}-\d{4}|\(\d{3}\) \d{3}-\d{4})',s))
    if qid==194:
        rows=[s.split() for s in text.splitlines()]
        if not rows or not rows[0] or any(len(r)!=len(rows[0]) for r in rows):raise ValueError('rectangular nonempty input required')
        return '\n'.join(' '.join(v) for v in zip(*rows))
    if qid==195:return text.splitlines()[9] if len(text.splitlines())>=10 else ''
    raise ValueError('shell oracle unavailable')


def controller_valid(qid,args):
    """Reviewed construction rules for identity/API tests; None means unknown."""
    def integer(v,lo,hi):return type(v) is int and lo<=v<=hi
    def ints(v,minimum,maximum,lo,hi):return type(v) is list and minimum<=len(v)<=maximum and all(integer(x,lo,hi) for x in v)
    from local.lab import javascript_protocol,javascript_async
    from local.lab import sql_answers
    if qid in sql_answers.QIDS:return sql_answers.valid(qid,args)
    if qid in javascript_async.QIDS:return javascript_async.valid(qid,args)
    if qid in javascript_protocol.QIDS:return javascript_protocol.valid(qid,args)
    if qid not in (142,160,843):return None
    if type(args) is not dict:return False
    if qid==142:
        return (set(args)=={'head','pos'} and ints(args['head'],0,10000,-100000,100000)
                and type(args['pos']) is int and (args['pos']==-1 or 0<=args['pos']<len(args['head'])))
    if qid==160:
        if set(args)!={'listA','listB','skipA','skipB','intersectVal'}:return False
        a,b,sa,sb,v=(args[k] for k in ('listA','listB','skipA','skipB','intersectVal'))
        if not ints(a,1,30000,1,100000) or not ints(b,1,30000,1,100000) or not integer(sa,0,len(a)) or not integer(sb,0,len(b)) or not integer(v,0,100000):return False
        return v==0 or (sa<len(a) and sb<len(b) and a[sa]==b[sb]==v and a[sa:]==b[sb:])
    if set(args)!={'secret','words','allowedGuesses'}:return False
    words=args['words']
    return (type(words) is list and 1<=len(words)<=100 and all(type(w) is str and re.fullmatch('[a-z]{6}',w) for w in words)
            and len(set(words))==len(words) and type(args['secret']) is str and args['secret'] in words and integer(args['allowedGuesses'],10,30))


def controller_answer(qid,args):
    from local.lab import sql_answers
    if qid in sql_answers.QIDS:return True,sql_answers.answer(qid,args)
    if qid==602:
        try:
            public=official(602)[0][0]['args'];check_database_input(qid,args,public)
            counts=friend_degrees(args);person=max(counts,key=counts.get)
            return True,{'columns':['id','num'],'rows':[[person,counts[person]]]}
        except (ValueError,TypeError,KeyError,IndexError):return False,None
    if qid not in (142,160,843):return False,None
    if controller_valid(qid,args) is not True:return False,None
    if qid==142:return True,{'node_index':None if args['pos']==-1 else args['pos']}
    if qid==160:return True,{'a_index':args['skipA'],'b_index':args['skipB']} if args['intersectVal'] else None
    return True,{'guessed':True}


def serialization_note(qid):
    from local.lab import javascript_protocol,javascript_async
    if qid in javascript_async.QIDS:return javascript_async.note(qid)+javascript_protocol.note(2626)
    if qid in javascript_protocol.QIDS:return javascript_protocol.note(qid)
    if kind(qid)=='database':
        from local.lab import sql_answers
        return ('Database inputs preserve declared column types: TEXT cells are strings even when displayed as digits; INTEGER cells are integers, never booleans. '
                'Preserve leading zeroes in TEXT and use null only for SQL NULL. Output column aliases are checked, except q177: '
                'its native contract returns a single scalar salary/null. The illustrated getNthHighestSalary(n) heading is a harness label, '
                'not candidate behavior; any one string column heading is accepted for q177 while row count, column count, value and type remain checked. '
                'The selected target language determines the SQL dialect: SQLite uses named :parameter inputs; native MySQL 8.0 uses @parameter session variables and the native stored-function interface for q177. Never mix the two dialects. '
                'For q180 ConsecutiveNums preserves VARCHAR Logs.num as a string; no numeric cast is implied by the sample display. '
                'For mutation tasks return the final table after executing the required mutation; do not substitute a SELECT solution.'+
                (' q602 MAIN task guarantees exactly ONE person with the most friends. Do not use tied, empty or follow-up cases. '
                 'The reviewed local input scope uses simple undirected friendships: self requests and reverse duplicates are unverified and not published. '
                 'Propose varied star-shaped or other unique-maximum graphs; a single edge and a cycle have tied maxima and are not legal main-task tests.' if qid==602 else '')+
                (' q1484 reviewed public correction: the input product is T-Shirt. Concatenation preserves that exact spelling; the displayed T-shirt output is a recorded example typo, not permission to lowercase product names.' if qid==1484 else '')+' '+sql_answers.note(qid))
    return {
        116:'The serialized result follows ACTUAL next pointers at every tree level, with the string "#" after each level. Next pointers must refer to the actual adjacent nodes and terminate at None; do not compute a breadth-first value list while ignoring next pointers.',
        117:'The serialized result follows ACTUAL next pointers at every tree level, with the string "#" after each level. Next pointers must refer to the actual adjacent nodes and terminate at None.',
        142:'pos constructs the input cycle, but is NOT a native method argument. Return {"node_index": index_or_null}, determined by identity of the returned original node, never its value. A fresh node with the same value is incorrect.',
        160:'intersectVal/skipA/skipB construct shared tail identity, not native method arguments. Return null for no intersection, otherwise {"a_index": i,"b_index": j} for the SAME actual returned node in each original list. Equal values alone do not imply intersection.',
        843:'secret/allowedGuesses construct Master, not additional native method arguments. Invoke the native solution with words and Master, count ALL guess calls including invalid words, and return {"guessed": true} only if Master actually observed a correct guess within the allowed budget. A no-op native solution must fail.',
        2886:'The output table MUST include a types array (INTEGER/REAL/TEXT) describing its columns as well as columns/rows. The grade column must become INTEGER; unchanged float dtype is not equivalent even when values are integral.',
    }.get(qid,'')


def input_valid_shape(value,*,max_items=300000):
    budget=[max_items]
    def walk(v,depth=0):
        budget[0]-=1
        if budget[0]<0 or depth>32:raise ValueError('test input exceeds size or nesting budget')
        if type(v) is dict:
            if any(type(k) is not str for k in v):raise ValueError('string object keys required')
            for child in v.values():walk(child,depth+1)
        elif type(v) is list:
            for child in v:walk(child,depth+1)
        elif type(v) is str:
            v.encode('utf8');budget[0]-=len(v)
        elif type(v) not in (int,float,bool,type(None)):raise ValueError('JSON input required')
        if type(v) is float and not __import__('math').isfinite(v):raise ValueError('finite input required')
    if type(value) is not dict:raise ValueError('input must be a JSON object')
    walk(value)
    if budget[0]<0:raise ValueError('test input exceeds size budget')
    return True
