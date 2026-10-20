"""Independent exhaustive checks for explicitly supported small inputs."""
from functools import lru_cache


def _other_expected(qid,args):
    if qid==1014:
        values=args['values']
        if len(set(values))==1:return 2*values[0]-1
        if len(values)<=200:return max(values[i]+values[j]+i-j for i in range(len(values)) for j in range(i+1,len(values)))
    if qid==1673:
        nums=args['nums'];k=args['k']
        if nums==sorted(nums):return nums[:k]
        if len(nums)<=16:
            from itertools import combinations
            return list(min(combinations(nums,k)))
    if qid==1957:
        from itertools import groupby
        return ''.join(char*min(2,sum(1 for _ in group)) for char,group in groupby(args['s']))
    if qid==2009:
        nums=args['nums'];n=len(nums)
        if len(set(nums))==n and max(nums)-min(nums)+1==n:return 0
        if n<=200:
            values=set(nums)
            starts=values|{x-n+1 for x in values}
            return n-max(sum(start<=x<start+n for x in values) for start in starts)
    if qid==1298 and len(args['status'])<=8:
        n=len(args['status'])
        # Enumerate all reachable sets of opened boxes, including every
        # opening order. Ownership and keys only grow with the opened set.
        todo=[0];seen={0};best=0
        while todo:
            opened=todo.pop();owned=set(args['initialBoxes']);unlocked=set()
            for i in range(n):
                if opened>>i&1:
                    owned.update(args['containedBoxes'][i]);unlocked.update(args['keys'][i])
            best=max(best,sum(args['candies'][i] for i in range(n) if opened>>i&1))
            for i in owned:
                if not opened>>i&1 and (args['status'][i] or i in unlocked):
                    new=opened|1<<i
                    if new not in seen:seen.add(new);todo.append(new)
        return best
    if qid==2145:
        # Every hidden sequence is a translation of these exact integer
        # offsets. Its allowable first values form one closed interval.
        offsets=[0]
        for d in args['differences']:offsets.append(offsets[-1]+d)
        return max(0,args['upper']-args['lower']-(max(offsets)-min(offsets))+1)
    if qid==2438 and len(args['queries'])<=1000:
        from math import prod
        powers=[1<<bit for bit in range(args['n'].bit_length()) if args['n']>>bit&1]
        return [prod(powers[left:right+1])%1000000007 for left,right in args['queries']]
    if qid==2537 and len(args['nums'])<=200:
        best=0
        for i in range(len(args['nums'])):
            frequencies={};pairs=0
            for x in args['nums'][i:]:
                pairs+=frequencies.get(x,0);frequencies[x]=frequencies.get(x,0)+1
                best+=pairs>=args['k']
        return best
    if qid==2588 and len(args['nums'])<=200:
        # A bit can be removed in pairs iff its count in the interval is even.
        count=0
        for i in range(len(args['nums'])):
            parity=0
            for x in args['nums'][i:]:parity^=x;count+=parity==0
        return count
    if qid==2616 and len(args['nums'])<=12:
        nums=args['nums']
        @lru_cache(None)
        def pairs(mask,remaining):
            if remaining==0:return 0
            if mask.bit_count()<2*remaining:return float('inf')
            bit=mask&-mask;i=bit.bit_length()-1;rest=mask^bit
            best=pairs(rest,remaining)
            for j in range(len(nums)):
                other=1<<j
                if rest&other:best=min(best,max(abs(nums[i]-nums[j]),pairs(rest^other,remaining-1)))
            return best
        return pairs((1<<len(nums))-1,args['p'])
    if qid==2580 and all(a==b for a,b in args['ranges']):
        return pow(2,len({a for a,b in args['ranges']}),1000000007)
    if qid==2070 and len(args['items'])*len(args['queries'])<=20000:
        return [max((b for p,b in args['items'] if p<=q),default=0) for q in args['queries']]
    if qid==2187 and len(set(args['time']))==1:
        return args['time'][0]*((args['totalTrips']+len(args['time'])-1)//len(args['time']))
    if qid==2187 and min(args['time'])*args['totalTrips']<=200000:
        for t in range(1,min(args['time'])*args['totalTrips']+1):
            if sum(t//x for x in args['time'])>=args['totalTrips']:return t
    if qid==2200 and len(args['nums'])<=1000:
        return [i for i in range(len(args['nums'])) if any(
            x==args['key'] and abs(i-j)<=args['k'] for j,x in enumerate(args['nums']))]
    if qid==2398 and len(args['chargeTimes'])<=200:
        a,b=args['chargeTimes'],args['runningCosts'];best=0
        for i in range(len(a)):
            for j in range(i+1,len(a)+1):
                if max(a[i:j])+(j-i)*sum(b[i:j])<=args['budget']:best=max(best,j-i)
        return best
    if qid==2580 and len(args['ranges'])<=200:
        ranges=args['ranges'];seen=set();components=0
        for i in range(len(ranges)):
            if i in seen:continue
            components+=1;todo=[i];seen.add(i)
            while todo:
                a=todo.pop()
                for b in range(len(ranges)):
                    if b not in seen and max(ranges[a][0],ranges[b][0])<=min(ranges[a][1],ranges[b][1]):
                        seen.add(b);todo.append(b)
        return pow(2,components,1000000007)
    if qid==2597 and len(args['nums'])<=18:
        nums=args['nums'];n=len(nums);conflicts=[0]*n
        for i in range(n):
            for j in range(n):
                if abs(nums[i]-nums[j])==args['k']:conflicts[i]|=1<<j
        valid=bytearray(1<<n);valid[0]=1
        for mask in range(1,1<<n):
            bit=mask&-mask;rest=mask^bit;i=bit.bit_length()-1
            valid[mask]=bool(valid[rest] and not conflicts[i]&rest)
        return sum(valid)-1
    if qid==2332 and max(args['buses'])<=300:
        buses=sorted(args['buses']);people=args['passengers'];best=1
        for t in range(1,max(buses)+1):
            if t in people:continue
            arrivals=sorted([(x,False) for x in people]+[(t,True)])
            pos=0;boarded=False
            for bus in buses:
                seats=args['capacity']
                while pos<len(arrivals) and seats and arrivals[pos][0]<=bus:
                    boarded|=arrivals[pos][1];pos+=1;seats-=1
            if boarded:best=t
        return best
    return None


def evaluate(qid: int, case: dict) -> dict:
    if qid != 2576:
        expected=_other_expected(qid,case['args']) if qid in {1014,1298,1673,1957,2009,2070,2145,2187,2200,2332,2398,2438,2537,2580,2588,2597,2616} else None
        if expected is None:return {'status': 'unsupported', 'reason': 'No bounded independent oracle for this input.'}
        return {'status': 'verified' if expected==case['expected'] else 'disagrees',
                'oracle': 'definition_or_structural_formula' if qid in {1014,1673,1957,2009,2145,2187,2580} else 'bounded_exhaustive_definition',
                'expected': expected}
    nums = case['args']['nums']
    if len(nums) > 16:
        return {'status': 'unsupported', 'reason': 'Exhaustive matching limited to 16 elements.'}

    @lru_cache(None)
    def matching(mask):
        if not mask:
            return 0
        bit = mask & -mask
        i = bit.bit_length()-1
        remaining = mask ^ bit
        best = matching(remaining)  # This index may remain unmarked.
        for j in range(len(nums)):
            partner = 1 << j
            if remaining & partner and (2*nums[i] <= nums[j] or 2*nums[j] <= nums[i]):
                best = max(best, 2 + matching(remaining ^ partner))
        return best

    expected = matching((1 << len(nums))-1)
    return {'status': 'verified' if expected == case['expected'] else 'disagrees',
            'oracle': 'exhaustive_disjoint_pair_matching', 'expected': expected,
            'states': matching.cache_info().currsize}
