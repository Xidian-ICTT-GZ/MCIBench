"""Repository-authored functional regressions, never model-generated answers.

Each mutation has a legal witness. It is admitted only after actual sandbox
execution returns WA on that witness. Correct variants delegate identically or
execute the reviewed algorithm directly; no textual rewriting of user code.
"""
from textwrap import indent
from local.lab.behavior import sha

VERSION = 'reviewed-functional-fixtures-v1'
# qid: (method, Python arguments, C++ return/arguments, argument names, bodies)
BASE = {
3: ('lengthOfLongestSubstring', 's: str', 'int', 'string s', 's',
'''left = 0
best = 0
seen = {}
for right, ch in enumerate(s):
    if ch in seen:
        left = max(left, seen[ch] + 1)
    seen[ch] = right
    best = max(best, right - left + 1)
return best''',
'''int left=0,best=0; map<char,int> seen;
for(int right=0;right<(int)s.size();++right){char ch=s[right];
 if(seen.count(ch)) left=max(left,seen[ch]+1);
 seen[ch]=right; best=max(best,right-left+1);
} return best;'''),
7: ('reverse','x: int','int','int x','x',
'''r = int(str(abs(x))[::-1]) * (-1 if x < 0 else 1)
if r < -2147483648 or r > 2147483647:
    return 0
return r''',
'''long long v=x,r=0; bool negative=v<0; if(negative)v=-v;
while(v){r=r*10+v%10;v/=10;} if(negative)r=-r;
if(r < -2147483648LL || r > 2147483647LL) return 0;
return (int)r;'''),
12: ('intToRoman','num: int','string','int num','num',
'''pairs = [(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]
out = []
for value, text in pairs:
    count, num = divmod(num, value)
    out.append(text * count)
return ''.join(out)''',
'''vector<pair<int,string>> pairs={{1000,"M"},{900,"CM"},{500,"D"},{400,"CD"},{100,"C"},{90,"XC"},{50,"L"},{40,"XL"},{10,"X"},{9,"IX"},{5,"V"},{4,"IV"},{1,"I"}};
string out; for(auto p:pairs){while(num>=p.first){out+=p.second;num-=p.first;}}return out;'''),
20: ('isValid','s: str','bool','string s','s',
'''stack = []
for ch in s:
    if ch in '([{':
        stack.append(ch)
    elif not stack or stack.pop() != {')':'(',']':'[','}':'{'}[ch]:
        return False
return not stack''',
'''string stack; map<char,char> pairs={{')','('},{']','['},{'}','{'}};
for(char ch:s){if(ch=='('||ch=='['||ch=='{')stack+=ch;
 else {if(stack.empty()||stack.back()!=pairs[ch])return false;stack.pop_back();}}
return stack.empty();'''),
33: ('search','nums: List[int], target: int','int','vector<int>& nums, int target','nums, target',
'''for i in range(len(nums)):
    if nums[i] == target:
        return i
return -1''',
'''for(int i=0;i<(int)nums.size();++i)if(nums[i]==target)return i;
return -1;'''),
41: ('firstMissingPositive','nums: List[int]','int','vector<int>& nums','nums',
'''seen = set(nums)
missing = 1
while missing in seen:
    missing += 1
return missing''',
'''set<int> seen(nums.begin(),nums.end()); int missing=1;
while(seen.count(missing))++missing;return missing;'''),
91: ('numDecodings','s: str','int','string s','s',
'''a, b = 1, int(s[0] != '0')
for i in range(1, len(s)):
    c = (b if s[i] != '0' else 0) + (a if 10 <= int(s[i-1:i+1]) <= 26 else 0)
    a, b = b, c
return b''',
'''unsigned __int128 a=1,b=s[0]!='0';
for(int i=1;i<(int)s.size();++i){int v=(s[i-1]-'0')*10+s[i]-'0';
 unsigned __int128 c=(s[i]!='0'?b:0)+(v>=10&&v<=26?a:0);a=b;b=c;}
return (int)b;'''),
125: ('isPalindrome','s: str','bool','string s','s',
'''text = ''.join(ch.lower() for ch in s if ch.isascii() and ch.isalnum())
return text == text[::-1]''',
'''string text;for(unsigned char ch:s)if(isalnum(ch))text+=(char)tolower(ch);
string other=text; std::reverse(other.begin(),other.end());return text==other;'''),
128: ('longestConsecutive','nums: List[int]','int','vector<int>& nums','nums',
'''ordered = sorted(set(nums))
best = streak = 0
previous = None
for v in ordered:
    streak = streak + 1 if previous is not None and v == previous + 1 else 1
    best = max(best, streak)
    previous = v
return best''',
'''set<int> unique(nums.begin(),nums.end());vector<int> ordered(unique.begin(),unique.end());
int best=0,streak=0,previous=0;bool have=false;
for(int v:ordered){streak=have&&v==previous+1?streak+1:1;best=max(best,streak);previous=v;have=true;}return best;'''),
172: ('trailingZeroes','n: int','int','int n','n',
'''total = 0
power = 5
while power <= n:
    total += n // power
    power *= 5
return total''',
'''int total=0;long long power=5;while(power<=n){total+=n/power;power*=5;}return total;'''),
231: ('isPowerOfTwo','n: int','bool','int n','n',
'''return n > 0 and (n & (n-1)) == 0''',
'''return n>0 && (((long long)n & ((long long)n-1))==0);'''),
263: ('isUgly','n: int','bool','int n','n',
'''if n <= 0:
    return False
for divisor in (2,3,5):
    while n % divisor == 0:
        n //= divisor
return n == 1''',
'''if(n<=0)return false;for(int divisor:{2,3,5})while(n%divisor==0)n/=divisor;return n==1;'''),
292: ('canWinNim','n: int','bool','int n','n',
'''return n % 4 != 0''',
'''return n%4!=0;'''),
509: ('fib','n: int','int','int n','n',
'''a, b = 0, 1
for _ in range(n):
    a, b = b, a+b
return a''',
'''int a=0,b=1;for(int i=0;i<n;++i){int c=a+b;a=b;b=c;}return a;'''),
1014: ('maxScoreSightseeingPair','values: List[int]','int','vector<int>& values','values',
'''best_left = values[0]
answer = 0
for j in range(1, len(values)):
    answer = max(answer, best_left + values[j] - j)
    best_left = max(best_left, values[j] + j)
return answer''',
'''int best_left=values[0],answer=0;for(int j=1;j<(int)values.size();++j){answer=max(answer,best_left+values[j]-j);best_left=max(best_left,values[j]+j);}return answer;'''),
}

# (error class, witness, Python old/new, C++ old/new). No mutation is admitted
# solely on this description: the audit must obtain a real WA on the witness.
MUTATIONS = {
3: [('stale_window',{'s':'abba'},'max(left, seen[ch] + 1)','seen[ch] + 1','max(left,seen[ch]+1)','seen[ch]+1'),
    ('length_off_by_one',{'s':'a'},'right - left + 1','right - left','right-left+1','right-left')],
7: [('lost_sign',{'x':-123},'(-1 if x < 0 else 1)','1','if(negative)r=-r;',''),
    ('overflow_clamped',{'x':1534236469},'return 0','return 2147483647','return 0;','return 2147483647;')],
12:[('wrong_subtractive_four',{'num':4},'(4,"IV")','(4,"IIII")','{4,"IV"}','{4,"IIII"}'),
    ('wrong_subtractive_ninety',{'num':90},'(90,"XC")','(90,"LXXXX")','{90,"XC"}','{90,"LXXXX"}')],
20:[('ignores_nesting',{'s':'([)]'},None,"return all(s.count(a) == s.count(b) for a,b in [('(',')'),('[',']'),('{','}')])",None,"return count(s.begin(),s.end(),'(')==count(s.begin(),s.end(),')') && count(s.begin(),s.end(),'[')==count(s.begin(),s.end(),']') && count(s.begin(),s.end(),'{')==count(s.begin(),s.end(),'}');"),
    ('unclosed_stack',{'s':'('},'return not stack','return True','return stack.empty();','return true;')],
33:[('unrotated_binary_search',{'nums':[4,5,1,2,3],'target':5},None,"lo, hi = 0, len(nums)-1\nwhile lo <= hi:\n    mid = (lo+hi)//2\n    if nums[mid] == target: return mid\n    if nums[mid] < target: lo = mid+1\n    else: hi = mid-1\nreturn -1",None,"int lo=0,hi=(int)nums.size()-1;while(lo<=hi){int mid=(lo+hi)/2;if(nums[mid]==target)return mid;if(nums[mid]<target)lo=mid+1;else hi=mid-1;}return -1;"),
    ('skips_last',{'nums':[1],'target':1},'range(len(nums))','range(len(nums)-1)','i<(int)nums.size()','i<(int)nums.size()-1')],
41:[('starts_at_zero',{'nums':[1,2]},'missing = 1','missing = 0','missing=1','missing=0'),
    ('missing_n_plus_one',{'nums':[1,2]},'while missing in seen:','while missing in seen and missing < len(nums):','while(seen.count(missing))','while(seen.count(missing) && missing<(int)nums.size())')],
91:[('leading_zero',{'s':'0'},"int(s[0] != '0')",'1',"b=s[0]!='0'",'b=1'),
    ('accepts_27',{'s':'27'},'<= 26','<= 27','v<=26','v<=27')],
125:[('case_sensitive',{'s':'Aa'},'ch.lower()','ch','(char)tolower(ch)','(char)ch'),
     ('drops_digits',{'s':'0P'},'ch.isalnum()','ch.isalpha()','isalnum(ch)','isalpha(ch)')],
128:[('duplicates_break_streak',{'nums':[1,2,2,3]},'sorted(set(nums))','sorted(nums)','vector<int> ordered(unique.begin(),unique.end());','vector<int> ordered=nums;sort(ordered.begin(),ordered.end());'),
     ('bridges_gap',{'nums':[1,3]},'v == previous + 1','v <= previous + 2','v==previous+1','v<=previous+2')],
172:[('misses_powers_of_five',{'n':25},None,'return n // 5',None,'return n/5;'),
     ('strict_upper_bound',{'n':5},'power <= n','power < n','power<=n','power<n')],
231:[('zero_is_power',{'n':0},'n > 0','n >= 0','n>0','n>=0'),
     ('ignores_sign',{'n':-2},None,'n = abs(n)\nreturn n > 0 and (n & (n-1)) == 0',None,'long long a=n;if(a<0)a=-a;return a>0&&(a&(a-1))==0;')],
263:[('omits_factor_five',{'n':5},'(2,3,5)','(2,3)','{2,3,5}','{2,3}'),
     ('accepts_factor_seven',{'n':7},'(2,3,5)','(2,3,5,7)','{2,3,5}','{2,3,5,7}')],
292:[('wrong_period',{'n':3},'n % 4','n % 3','n%4','n%3'),
     ('inverted_winner',{'n':4},'!= 0','== 0','!=0','==0')],
509:[('wrong_base',{'n':0},'a, b = 0, 1','a, b = 1, 1','a=0,b=1','a=1,b=1'),
     ('one_iteration_short',{'n':3},'range(n)','range(max(0,n-1))','i<n','i<n-1')],
1014:[('wrong_distance_sign',{'values':[1,1]},'values[j] - j','values[j] + j','values[j]-j','values[j]+j'),
      ('skips_second',{'values':[10,9,1]},'range(1, len(values))','range(2, len(values))','int j=1;','int j=2;')],
}


def source(qid, language, body, *, delegated=False):
    method, pyargs, ret, cppargs, names, _, _ = BASE[qid]
    if language == 'python3':
        header = 'from typing import List\n\nclass Solution:\n'
        if delegated:
            header += f'    def {method}(self, {pyargs}):\n        return self._evaluate({names})\n'
            method = '_evaluate'
        return header + f'    def {method}(self, {pyargs}):\n' + indent(body, '        ') + '\n'
    if language != 'cpp':
        raise ValueError('fixtures are authored for Python3 and C++ only')
    header = '#include <bits/stdc++.h>\nusing namespace std;\nclass Solution { public:\n'
    if delegated:
        header += f'{ret} {method}({cppargs}) {{ return evaluate({names}); }}\n'
        method = 'evaluate'
    return header + f'{ret} {method}({cppargs}) {{\n{body}\n}}\n}};\n'


def fixtures(qid):
    out = []
    for language, column in (('python3',5),('cpp',6)):
        baseline = BASE[qid][column]
        for number, delegated in enumerate((False, True), 1):
            code = source(qid, language, baseline, delegated=delegated)
            out.append({'id':f'q{qid}-{language}-correct-{number}', 'qid':qid, 'language':language,
                        'role':'correct', 'error_class':None, 'equivalence':'reviewed_algorithm' if not delegated else 'single_call_delegation',
                        'code':code, 'code_sha256':sha(code)})
        for mutation in MUTATIONS[qid]:
            name, witness = mutation[:2]
            before, after = mutation[2:4] if language == 'python3' else mutation[4:6]
            if before is not None and baseline.count(before) != 1:
                raise ValueError(f'q{qid}/{language}/{name}: mutation anchor not unique')
            code = source(qid, language, after if before is None else baseline.replace(before, after))
            out.append({'id':f'q{qid}-{language}-{name}', 'qid':qid, 'language':language,
                        'role':'incorrect', 'error_class':name, 'witness':witness,
                        'code':code, 'code_sha256':sha(code)})
    return out
