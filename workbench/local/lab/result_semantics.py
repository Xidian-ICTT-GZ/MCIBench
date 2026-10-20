"""Repository-owned result predicates for common non-unique answer contracts.

None means no reviewed predicate is available. It must never mean acceptance.
This lab extension does not modify frozen historical comparison rules.
"""
from collections import Counter
from pathlib import Path
from local.lab import source_guard
source_guard.register(__file__)

VERSION='lab-result-semantics-v1'
ALL_UNORDERED={15,18,39,40,49,77,78,90,216}
ROWS_UNORDERED={46,47,131}
FLAT_UNORDERED={17,140,187,229,260,301,310,347,349,350,442,448,500,599}


def _ints(values):return type(values) is list and all(type(v) is int for v in values)


def valid(qid,got,args):
    if qid in (1,167):
        if not _ints(got) or len(got)!=2:return False
        nums=args['nums'] if qid==1 else args['numbers'];indices=[i-(qid==167) for i in got]
        return all(0<=i<len(nums) for i in indices) and indices[0]!=indices[1] and (qid!=167 or indices[0]<indices[1]) and nums[indices[0]]+nums[indices[1]]==args['target']
    if qid==5:
        s=args['s']
        if type(got) is not str or got!=got[::-1] or got not in s:return False
        best=0
        for i in range(len(s)):
            for left,right in ((i,i),(i,i+1)):
                while left>=0 and right<len(s) and s[left]==s[right]:best=max(best,right-left+1);left-=1;right+=1
        return len(got)==best
    if qid==210:
        n=args['numCourses'];edges=args['prerequisites'];indeg=[0]*n;adj=[[] for _ in range(n)]
        for a,b in edges:adj[b].append(a);indeg[a]+=1
        todo=[i for i in range(n) if not indeg[i]];seen=0
        while todo:
            node=todo.pop();seen+=1
            for other in adj[node]:
                indeg[other]-=1
                if not indeg[other]:todo.append(other)
        if seen<n:return got==[]
        if not _ints(got) or len(got)!=n or set(got)!=set(range(n)):return False
        pos={v:i for i,v in enumerate(got)}
        return all(pos[b]<pos[a] for a,b in edges)
    if qid==347:
        if not _ints(got) or len(got)!=args['k'] or len(set(got))!=len(got):return False
        counts=Counter(args['nums'])
        if any(x not in counts for x in got):return False
        return min(counts[x] for x in got)>=max((n for x,n in counts.items() if x not in set(got)),default=0)
    if qid in (451,767,984,1054,1405):
        if qid==1054:
            return _ints(got) and Counter(got)==Counter(args['barcodes']) and all(a!=b for a,b in zip(got,got[1:]))
        if type(got) is not str:return False
        if qid==451:
            counts=Counter(args['s'])
            blocks=[c for i,c in enumerate(got) if i==0 or got[i-1]!=c]
            return Counter(got)==counts and len(blocks)==len(set(blocks)) and [counts[c] for c in blocks]==sorted((counts[c] for c in blocks),reverse=True)
        if qid==767:
            counts=Counter(args['s'])
            if max(counts.values(),default=0)>(len(args['s'])+1)//2:return got==''
            return Counter(got)==counts and all(a!=b for a,b in zip(got,got[1:]))
        counts={'a':args['a'],'b':args['b']}
        if qid==1405:counts['c']=args['c']
        actual=Counter(got)
        if any(c not in counts or n>counts[c] for c,n in actual.items()) or any(got[i]==got[i+1]==got[i+2] for i in range(len(got)-2)):return False
        total=sum(counts.values())
        if qid==984:return len(got)==total
        return len(got)==min(total,3*(total-max(counts.values()))+2)
    if qid==1092:
        if type(got) is not str:return False
        a,b=args['str1'],args['str2']
        def subsequence(s,t):
            i=0
            for c in t:
                if i<len(s) and s[i]==c:i+=1
            return i==len(s)
        if not subsequence(a,got) or not subsequence(b,got):return False
        dp=[0]*(len(b)+1)
        for x in a:
            previous=0
            for j,y in enumerate(b,1):
                old=dp[j];dp[j]=previous+1 if x==y else max(dp[j],dp[j-1]);previous=old
        return len(got)==len(a)+len(b)-dp[-1]
    # Reuse only repository-owned trusted predicates; never execute model code
    # on the host. Their return type is an integer array or integer matrix.
    from local.harness import validators
    if validators.has_validator(qid):
        if not _ints(got) and not (type(got) is list and all(_ints(r) for r in got)):return False
        namespace={};exec(validators.helper('python3',qid),namespace)
        try:return bool(namespace['_valid'](got,*(args[p] for p in validators.VALIDATOR_PARAMS[validators.ANSWER_VALIDATORS[qid]])))
        except (ValueError,TypeError,KeyError,IndexError):return False
    return None


def mode(qid,fallback):
    if qid in ALL_UNORDERED:return 'all_unordered'
    if qid in ROWS_UNORDERED:return 'rows_unordered'
    if qid in FLAT_UNORDERED:return 'unordered'
    return fallback
