"""Reviewed SQL answer controllers; explicit finite scope and decimal profile."""
from collections import defaultdict
from collections import Counter
from fractions import Fraction
from datetime import date
import math
import re
import struct

from local.lab import source_guard
from local.lab import sql_review_batch8 as reviewed8
source_guard.register(__file__)

VERSION='reviewed-sql-exact-rates-and-official-text-v4'
QIDS={1179,1211,1517,1633,1661,1693,1789,1873}|reviewed8.QIDS
MAX_ROWS={1179:2000,1211:2000,1517:2000,1633:20000,1661:2000,1693:2000,1789:2000,1873:2000,**{q:2000 for q in reviewed8.QIDS}}
MONTHS=('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
NUMERIC_PROFILE='mysql-int-div4-avg8-positive-half-up2-v1'
PERCENT_PROFILE='mysql-count-times-decimal100-div5-half-up2-v1'
ACTIVITY_PROFILE='mysql-float32-exact-durations-binary64-avg-rint3-v1'
DATE_PROFILE='declared-date-canonical-iso-calendar-v1'


def canonical_day(value):
    if value is None:return None
    if type(value) is not str:raise ValueError('declared non-NULL DATE must be a string')
    match=re.fullmatch(r'([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})',value)
    if not match:raise ValueError('DATE representation outside reviewed year-month-day scope')
    year,month,day=map(int,match.groups())
    if year<1000:raise ValueError('DATE year outside reviewed native range; remains unverified')
    return date(year,month,day).isoformat()


def extra_valid(qid,args):
    columns={1517:{'Users':['user_id','name','mail']},
             1633:{'Users':['user_id','user_name'],'Register':['contest_id','user_id']},
             1661:{'Activity':['machine_id','process_id','activity_type','timestamp']},
             1693:{'DailySales':['date_id','make_name','lead_id','partner_id']},
             1789:{'Employee':['employee_id','department_id','primary_flag']},
             1873:{'Employees':['employee_id','name','salary']}}[qid]
    if set(args['tables'])!=set(columns):return False
    for name,names in columns.items():
        table=args['tables'][name]
        if type(table) is not dict or table.get('columns')!=names or type(table.get('rows')) is not list:return False
        if len(table['rows'])>MAX_ROWS[qid]:raise ValueError('reviewed SQL row scope exceeded; larger legal inputs remain unverified')
        if any(type(row) is not list or len(row)!=len(names) for row in table['rows']):return False
    def integer(v):return type(v) is int and -(2**31)<=v<2**31
    if qid==1693:
        for day,name,lead,partner in args['tables']['DailySales']['rows']:
            if canonical_day(day)!=day:raise ValueError('DATE transport requires explicit canonical ISO normalization; the original valid date is not forbidden')
            if type(name) is not str or not name or any(not 'a'<=c<='z' for c in name):return False
            if any(v is not None and not integer(v) for v in (lead,partner)):return False
        return True
    if qid==1789:
        grouped=defaultdict(list);keys=set()
        for employee,department,flag in args['tables']['Employee']['rows']:
            if not integer(employee) or not integer(department) or flag not in ('Y','N') or (employee,department) in keys:return False
            keys.add((employee,department));grouped[employee].append(flag)
        return all(flags==['N'] if len(flags)==1 else flags.count('Y')==1 for flags in grouped.values())
    if qid==1873:
        seen=set()
        for employee,name,salary in args['tables']['Employees']['rows']:
            if not integer(employee) or employee in seen or name is not None and type(name) is not str or salary is not None and not integer(salary):return False
            seen.add(employee)
        return True
    if qid in (1517,1633):
        users=args['tables']['Users']['rows'];seen=set()
        if len(users)>2000:raise ValueError('reviewed user scope is at most 2000 rows')
        for row in users:
            if not integer(row[0]) or row[0] in seen or any(v is not None and type(v) is not str for v in row[1:]):return False
            seen.add(row[0])
        if qid==1633:
            pairs=set()
            for contest,user in args['tables']['Register']['rows']:
                if not integer(contest) or not integer(user) or user not in seen or (contest,user) in pairs:return False
                pairs.add((contest,user))
        return True
    events={}
    for machine,process,kind,timestamp in args['tables']['Activity']['rows']:
        if not integer(machine) or not integer(process) or kind not in ('start','end') or type(timestamp) not in (int,float) or not math.isfinite(timestamp):return False
        key=(machine,process)
        if kind in events.setdefault(key,{}):return False
        events[key][kind]=timestamp
    counts=Counter()
    for (machine,process),pair in events.items():
        if set(pair)!={'start','end'} or pair['start']>=pair['end']:return False
        counts[machine]+=1
    if len(set(counts.values()))>1:return False
    activity_durations(args)  # Also prove native representation/summation scope.
    return True


def activity_durations(args):
    grouped=defaultdict(dict)
    for machine,process,kind,timestamp in args['tables']['Activity']['rows']:
        try:value=struct.unpack('!f',struct.pack('!f',timestamp))[0]
        except (OverflowError,struct.error):raise ValueError('timestamp outside native FLOAT32 scope') from None
        if not math.isfinite(value):raise ValueError('timestamp outside native finite FLOAT32 scope')
        grouped[(machine,process)][kind]=Fraction.from_float(value)
    durations=defaultdict(list)
    for (machine,process),pair in grouped.items():
        duration=pair['end']-pair['start']
        if duration<=0:raise ValueError('start/end collapse under native FLOAT32 representation; remains unverified')
        durations[machine].append(duration)
    for values in durations.values():
        # All binary fractions share a power-of-two denominator. This bound
        # proves every positive partial sum is exact in binary64, independent
        # of SQL row order, before AVG's single binary64 division.
        denominator=max(v.denominator for v in values)
        ticks=sum(v.numerator*(denominator//v.denominator) for v in values)
        if ticks>2**53:raise ValueError('native binary64 accumulation not proved exact in reviewed scope')
    return durations


def valid(qid,args):
    if qid not in QIDS:return None
    if qid in reviewed8.QIDS:return reviewed8.valid(qid,args)
    if type(args) is not dict or set(args)!={'tables'} or type(args['tables']) is not dict:return False
    if qid in (1517,1633,1661,1693,1789,1873):return extra_valid(qid,args)
    name='Department' if qid==1179 else 'Queries'
    names=['id','revenue','month'] if qid==1179 else ['query_name','result','position','rating']
    if set(args['tables'])!={name}:return False
    table=args['tables'][name]
    if type(table) is not dict or table.get('columns')!=names or type(table.get('rows')) is not list:return False
    rows=table['rows']
    if len(rows)>2000:raise ValueError('reviewed SQL oracle scope is at most 2000 rows; larger legal inputs remain unverified')
    if any(type(row) is not list or len(row)!=len(names) for row in rows):return False
    if qid==1179:
        keys=set()
        for ident,revenue,month in rows:
            if type(ident) is not int or not -(2**31)<=ident<2**31 or month not in MONTHS:return False
            if revenue is not None and (type(revenue) is not int or not -(2**31)<=revenue<2**31):return False
            if (ident,month) in keys:return False
            keys.add((ident,month))
        return True
    spellings={}
    for name,result,position,rating in rows:
        if name is not None:
            if type(name) is not str:return False
            if not re.fullmatch(r'[A-Za-z0-9_]+',name):
                raise ValueError('q1211 non-ASCII/punctuation collation is outside the reviewed oracle scope, not claimed forbidden by the statement')
            if name.casefold() in spellings and spellings[name.casefold()]!=name:
                raise ValueError('q1211 mixed case-equivalent group names are outside the reviewed collation scope')
            spellings[name.casefold()]=name
        if result is not None and type(result) is not str:return False
        if type(position) is not int or not 1<=position<=500 or type(rating) is not int or not 1<=rating<=5:return False
    return True


def rounded_ratio(numerator,denominator):
    """Round a nonnegative rational to an integer without binary floats."""
    quotient,remainder=divmod(numerator,denominator)
    return quotient+(2*remainder>=denominator)


def answer(qid,args):
    if valid(qid,args) is not True:raise ValueError('reviewed SQL controller rejected input')
    if qid in reviewed8.QIDS:return reviewed8.answer(qid,args)
    if qid==1693:
        groups={}
        for day,name,lead,partner in args['tables']['DailySales']['rows']:
            left,right=groups.setdefault((day,name),(set(),set()))
            if lead is not None:left.add(lead)
            if partner is not None:right.add(partner)
        return {'columns':['date_id','make_name','unique_leads','unique_partners'],
                'rows':[[day,name,len(left),len(right)] for (day,name),(left,right) in sorted(groups.items(),key=lambda item:(item[0][0] is not None,item[0][0] or '',item[0][1]))]}
    if qid==1789:
        groups=defaultdict(list)
        for employee,department,flag in args['tables']['Employee']['rows']:groups[employee].append((department,flag))
        return {'columns':['employee_id','department_id'],
                'rows':[[employee,items[0][0] if len(items)==1 else next(d for d,f in items if f=='Y')] for employee,items in sorted(groups.items())]}
    if qid==1873:
        return {'columns':['employee_id','bonus'],
                'rows':[[employee,salary if employee&1 and name is not None and name[:1]!='M' else 0]
                        for employee,name,salary in sorted(args['tables']['Employees']['rows'])]}
    if qid==1517:
        def email(value):
            if type(value) is not str or not value.endswith('@leetcode.com'):return False
            prefix=value[:-13]
            return bool(prefix) and prefix[0] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-' for c in prefix)
        return {'columns':['user_id','name','mail'],'rows':[list(row) for row in args['tables']['Users']['rows'] if email(row[2])]}
    if qid==1633:
        total=len(args['tables']['Users']['rows']);counts=Counter(row[0] for row in args['tables']['Register']['rows'])
        rows=[[contest,rounded_ratio(rounded_ratio(count*100*100000,total),1000)/100] for contest,count in counts.items()]
        return {'columns':['contest_id','percentage'],'rows':sorted(rows,key=lambda row:(-row[1],row[0]))}
    if qid==1661:
        rows=[[machine,round(float(sum(values)/len(values))*1000)/1000] for machine,values in activity_durations(args).items()]
        return {'columns':['machine_id','processing_time'],'rows':sorted(rows)}
    if qid==1179:
        grouped={}
        for ident,revenue,month in args['tables']['Department']['rows']:
            grouped.setdefault(ident,{})[month]=revenue
        return {'columns':['id']+[m+'_Revenue' for m in MONTHS],
                'rows':[[ident]+[grouped[ident].get(m) for m in MONTHS] for ident in sorted(grouped)]}
    grouped=defaultdict(list)
    for name,result,position,rating in args['tables']['Queries']['rows']:grouped[name].append((position,rating))
    rows=[]
    for name,values in grouped.items():
        n=len(values)
        # MySQL 8.0: INT / INT -> DECIMAL scale 4, AVG -> scale 8.
        # The explicit SUM(...)*100.0/COUNT(*) percentage has scale 5.
        ratios=sum(rounded_ratio(rating*10000,position) for position,rating in values)
        avg8=rounded_ratio(ratios*10000,n)
        quality_cents=rounded_ratio(avg8,1000000)
        percent5=rounded_ratio(sum(rating<3 for _,rating in values)*100*100000,n)
        percent_cents=rounded_ratio(percent5,1000)
        rows.append([name,quality_cents/100,percent_cents/100])
    return {'columns':['query_name','quality','poor_query_percentage'],'rows':rows}


def expand_pivot_public(args,shown,statement):
    excerpts=['The revenue from Apr to Dec is null.',
              'the result table has 13 columns (1 for the department id + 12 for the months).']
    if any(s not in statement for s in excerpts):raise ValueError('q1179 omitted columns lack explicit statement evidence')
    full=answer(1179,args)
    keep=[i for i,c in enumerate(shown['columns']) if c!='...']
    projected=[[row[full['columns'].index(shown['columns'][i])] for i in keep] for row in full['rows']]
    if projected!=[[row[i] for i in keep] for row in shown['rows']]:
        raise ValueError('q1179 expanded columns disagree with visible public values')
    return full,excerpts


def note(qid):
    if qid in reviewed8.QIDS:return reviewed8.note(qid)
    if qid==1179:return 'q1179 has EXACTLY 13 output columns: id and Jan_Revenue through Dec_Revenue. The public ellipsis is presentation only. Missing months are SQL NULL, never a literal "..." cell. The reviewed independent pivot oracle supports at most 2000 input rows.'
    if qid==1211:return ('q1211 numeric profile '+NUMERIC_PROFILE+': emulate native MySQL 8.0 INT/INT decimal division at scale 4, AVG at scale 8, and positive half-up rounding to two places. The percentage expression is SUM(rating<3)*100.0/COUNT(*), scale 5 before the final rounding. Do not use binary Python round. Reviewed scope: at most 2000 rows, null or ASCII alphanumeric/underscore query names without mixed case-equivalent spellings. Other legal name/collation families remain unverified.')
    if qid==1517:return 'q1517 requires an ASCII letter first, then only ASCII letters/digits/underscore/period/dash, and the EXACT case-sensitive domain @leetcode.com. No trailing newline or whitespace is valid. Use native REGEXP_LIKE match_type c plus an exact suffix guard. Reviewed scope: at most 2000 users.'
    if qid==1633:return 'q1633 numeric profile '+PERCENT_PROFILE+': native COUNT*100.0/total uses DECIMAL scale 5 before positive half-up rounding to two places. Python round uses a different tie rule. Reviewed scope: at most 2000 users and 20000 registrations, unique primary keys and existing users. This finite native profile is explicit; other SQL expression precision choices are not assumed equivalent.'
    if qid==1661:return 'q1661 numeric profile '+ACTIVITY_PROFILE+': timestamp is native MySQL FLOAT (IEEE binary32), including when solving in another language. Convert EACH input timestamp to binary32 before subtracting. Average durations in binary64 and round via nearest-even rint(value*1000)/1000, matching native approximate ROUND. This can differ from exact-decimal task arithmetic. Scope: at most 2000 events, complete start/end pairs, equal process counts per machine, preserved positive duration after FLOAT32 conversion, and independently proved exact binary64 partial sums; other legal numeric families remain unverified.'
    if qid==1693:return 'q1693 DATE profile '+DATE_PROFILE+': date_id is declared DATE, not arbitrary TEXT. Inputs and outputs use canonical YYYY-MM-DD, preserving calendar values such as 2020-12-8 = 2020-12-08. make_name contains lowercase English letters. Count distinct non-NULL lead/partner IDs separately; duplicate input rows are legal. Scope: at most 2000 rows and reviewed native DATE years 1000..9999.'
    if qid==1789:return 'q1789: an employee with exactly ONE department MUST have primary_flag N, as explicitly stated. Multiple departments require exactly one primary Y; flags are Y/N and (employee_id,department_id) is unique. Single-department Y is not a legal test. Scope: at most 2000 rows.'
    if qid==1873:return 'q1873 uses the literal uppercase character M, case-sensitive in this portable contract. A lowercase m does not start with uppercase M. MySQL must use an explicit binary collation for this predicate. Odd means nonzero remainder, including signed integer representation. Scope: at most 2000 rows. Equivalence to LC collation settings has not been established.'
    return ''


PIVOT_PY='''def solve(data):
 months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
 groups={}
 for ident,revenue,month in data['tables']['Department']['rows']:
  groups.setdefault(ident,{})[month]=revenue
 return {'columns':['id']+[m+'_Revenue' for m in months], 'rows':[[ident]+[groups[ident].get(m) for m in months] for ident in sorted(groups)]}
'''

DECIMAL_PY='''from decimal import Decimal,localcontext,ROUND_HALF_UP
def solve(data):
 groups={}
 for name,result,position,rating in data['tables']['Queries']['rows']:
  groups.setdefault(name,[]).append((position,rating))
 rows=[]
 with localcontext() as context:
  context.prec=50
  def rounded(v,scale):return v.quantize(Decimal(1).scaleb(-scale),rounding=ROUND_HALF_UP)
  for name,values in groups.items():
   n=Decimal(len(values))
   ratios=[rounded(Decimal(r)/Decimal(p),4) for p,r in values]
   quality=rounded(rounded(sum(ratios)/n,8),2)
   percent=rounded(rounded(Decimal(sum(r<3 for _,r in values))*Decimal('100.0')/n,5),2)
   rows.append([name,float(quality),float(percent)])
 return {'columns':['query_name','quality','poor_query_percentage'],'rows':rows}
'''


def reference(qid,language):
    if qid in reviewed8.QIDS:return reviewed8.reference(qid,language)
    if qid==1693:
        if language=='python3':return "from collections import defaultdict\ndef solve(data):\n leads=defaultdict(set); partners=defaultdict(set)\n for day,name,lead,partner in data['tables']['DailySales']['rows']:\n  key=(day,name); leads[key]; partners[key]\n  if lead is not None:leads[key].add(lead)\n  if partner is not None:partners[key].add(partner)\n return {'columns':['date_id','make_name','unique_leads','unique_partners'],'rows':[[d,n,len(leads[(d,n)]),len(partners[(d,n)])] for d,n in leads]}\n"
        if language in ('mysql','sqlite'):return 'SELECT date_id,make_name,COUNT(DISTINCT lead_id) AS unique_leads,COUNT(DISTINCT partner_id) AS unique_partners FROM DailySales GROUP BY date_id,make_name'
    if qid==1789:
        if language=='python3':return "from collections import defaultdict\ndef solve(data):\n grouped=defaultdict(list)\n for e,d,f in data['tables']['Employee']['rows']:grouped[e].append((d,f))\n return {'columns':['employee_id','department_id'],'rows':[[e,d] for e,items in grouped.items() for d,f in items if len(items)==1 or f=='Y']}\n"
        if language in ('mysql','sqlite'):return "SELECT employee_id,department_id FROM Employee WHERE primary_flag='Y' OR employee_id IN (SELECT employee_id FROM Employee GROUP BY employee_id HAVING COUNT(*)=1)"
    if qid==1873:
        if language=='python3':return "def solve(data):\n return {'columns':['employee_id','bonus'],'rows':[[e,s if e%2!=0 and n is not None and not n.startswith('M') else 0] for e,n,s in sorted(data['tables']['Employees']['rows'])]}\n"
        if language=='sqlite':return "SELECT employee_id,CASE WHEN employee_id%2<>0 AND substr(name,1,1) COLLATE BINARY <> 'M' THEN salary ELSE 0 END AS bonus FROM Employees ORDER BY employee_id"
        if language=='mysql':return "SELECT employee_id,CASE WHEN MOD(employee_id,2)<>0 AND LEFT(name,1) COLLATE utf8mb4_0900_bin <> 'M' THEN salary ELSE 0 END AS bonus FROM Employees ORDER BY employee_id"
    if qid==1517:
        if language=='python3':return "import re\ndef solve(data):\n return {'columns':['user_id','name','mail'],'rows':[row for row in data['tables']['Users']['rows'] if isinstance(row[2],str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*@leetcode[.]com',row[2])]}\n"
        if language=='mysql':return "SELECT user_id,name,mail FROM Users WHERE REGEXP_LIKE(mail,'^[A-Za-z][A-Za-z0-9_.-]*@leetcode[.]com$','c') AND RIGHT(mail,13) COLLATE utf8mb4_bin='@leetcode.com'"
        if language=='sqlite':return "SELECT user_id,name,mail FROM Users WHERE mail REGEXP '^[A-Za-z][A-Za-z0-9_.-]*@leetcode[.]com$' AND substr(mail,-13)='@leetcode.com'"
    if qid==1633:
        if language=='python3':return "from collections import Counter\nfrom decimal import Decimal,ROUND_HALF_UP\ndef solve(data):\n n=len(data['tables']['Users']['rows']); counts=Counter(c for c,u in data['tables']['Register']['rows']); rows=[]\n for c,k in counts.items():\n  p=(Decimal(k)*Decimal('100.0')/Decimal(n)).quantize(Decimal('.00001'),rounding=ROUND_HALF_UP).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)\n  rows.append([c,float(p)])\n return {'columns':['contest_id','percentage'],'rows':sorted(rows,key=lambda r:(-r[1],r[0]))}\n"
        if language=='mysql':return 'SELECT contest_id,ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM Users),2) AS percentage FROM Register GROUP BY contest_id ORDER BY percentage DESC,contest_id'
    if qid==1661:
        if language=='python3':return "import struct\nfrom collections import defaultdict\ndef solve(data):\n pairs=defaultdict(dict); machines=defaultdict(list)\n for m,p,k,t in data['tables']['Activity']['rows']:pairs[(m,p)][k]=struct.unpack('!f',struct.pack('!f',t))[0]\n for (m,p),v in pairs.items():machines[m].append(v['end']-v['start'])\n return {'columns':['machine_id','processing_time'],'rows':[[m,round(sum(v)/len(v)*1000)/1000] for m,v in sorted(machines.items())]}\n"
        if language=='mysql':return "SELECT a.machine_id,ROUND(AVG(b.timestamp-a.timestamp),3) AS processing_time FROM Activity a JOIN Activity b ON a.machine_id=b.machine_id AND a.process_id=b.process_id AND a.activity_type='start' AND b.activity_type='end' GROUP BY a.machine_id"
    if qid==1179:
        if language=='python3':return PIVOT_PY
        if language in ('mysql','sqlite'):
            return 'SELECT id,'+','.join("SUM(CASE WHEN month='"+m+"' THEN revenue END) AS "+m+'_Revenue' for m in MONTHS)+' FROM Department GROUP BY id'
    if qid==1211:
        if language=='python3':return DECIMAL_PY
        if language=='mysql':return ('SELECT query_name, ROUND(AVG(rating / position),2) AS quality, '
            'ROUND(SUM(CASE WHEN rating<3 THEN 1 ELSE 0 END)*100.0/COUNT(*),2) AS poor_query_percentage FROM Queries GROUP BY query_name')
    return None
