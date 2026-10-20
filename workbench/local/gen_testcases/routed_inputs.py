"""Construct legal inputs for reviewed discrepancy targets, not relaxed bounds."""


SUPPORTED = {1014,1298,1673,1957,2009,2070,2145,2187,2200,2332,2398,2438,2537,2580,2588,2597,2616}


def generate(qid, rng, mode):
    edge = mode == 'boundary'
    n = rng.randint(1,18 if not edge else 48)
    pick = lambda limit: rng.choice([1,2,limit-1,limit]) if edge else rng.randint(1,min(30,limit))
    if mode == 'large':
        if qid == 1014:return {'values':[1000]*50000}
        if qid == 1673:return {'nums':list(range(100000)),'k':50000}
        if qid == 1957:return {'s':('abc'*33333)+'a'}
        if qid == 2009:return {'nums':list(range(1,100001))}
        if qid == 1298:return {'status':[0]*999+[1],'candies':[1000]*1000,
                              'keys':[[]]+[[i-1] for i in range(1,1000)],
                              'containedBoxes':[[] for _ in range(1000)],'initialBoxes':list(range(1000))}
        if qid == 2145:return {'differences':[100000]*21475,'lower':100000,'upper':100000}
        if qid == 2070:return {'items':[[i+1,(i%997)+1] for i in range(100000)],'queries':list(range(1,100001))}
        if qid == 2187:return {'time':[10000000]*100000,'totalTrips':10000000}
        if qid == 2398:return {'chargeTimes':[100000]*50000,'runningCosts':[100000]*50000,'budget':10**15}
        if qid == 2580:return {'ranges':[[2*i,2*i] for i in range(100000)]}
        if qid == 2332:return {'buses':list(range(2,200002,2)),'passengers':list(range(3,200003,2)),'capacity':1}
        if qid == 2597:return {'nums':[1,2,3]*6,'k':1}
        if qid == 2200:return {'nums':[1]*999+[1000],'key':1000,'k':1}
        if qid == 2438:return {'n':1000000000,'queries':[[0,12]]*100000}
        if qid == 2537:return {'nums':[1000000000]*100000,'k':1000000000}
        if qid == 2588:return {'nums':[1000000,1]*50000}
        if qid == 2616:return {'nums':list(range(100000)),'p':50000}
    if qid == 1298:
        n=min(n,8)
        children=[[] for _ in range(n)]
        for child in range(1,n):
            if rng.randrange(3):children[rng.randrange(child)].append(child)
        return {'status':[rng.randrange(2) for _ in range(n)],'candies':[pick(1000) for _ in range(n)],
                'keys':[rng.sample(range(n),rng.randrange(n+1)) for _ in range(n)],
                'containedBoxes':children,'initialBoxes':rng.sample(range(n),rng.randrange(n+1))}
    if qid == 1014:return {'values':[pick(1000) for _ in range(max(2,n))]}
    if qid == 1673:return {'nums':[pick(1000000000)-1 for _ in range(min(n,16))],'k':rng.randint(1,min(n,16))}
    if qid == 1957:return {'s':''.join(rng.choice('aabc') for _ in range(n))}
    if qid == 2009:return {'nums':[pick(1000000000) for _ in range(n)]}
    if qid == 2145:return {'differences':[rng.randint(-100000,100000) for _ in range(n)],
                          'lower':-100000 if edge else -30,'upper':100000 if edge else 30}
    if qid == 2070:
        prices=[pick(10**9) for _ in range(n)]
        return {'items':[[x,pick(10**9)] for x in prices],
                'queries':[rng.choice(prices+[1,10**9]) for _ in range(rng.randint(1,18))]}
    if qid == 2187:return {'time':[pick(10**7) for _ in range(min(n,18))],'totalTrips':pick(10**7)}
    if qid == 2200:
        nums=[pick(1000) for _ in range(n)]
        return {'nums':nums,'key':rng.choice(nums),'k':rng.randint(1,n)}
    if qid == 2332:
        pool = list(range(2,110)) if not edge else list(range(2,70))+list(range(10**9-70,10**9+1))
        return {'buses':rng.sample(pool,n),'passengers':rng.sample(pool,rng.randint(1,48)),
                'capacity':rng.randint(1,48)}
    if qid == 2398:
        charges=[pick(100000) for _ in range(n)];costs=[pick(100000) for _ in range(n)]
        # Probe actual window boundaries. Uniform million-sized budgets made
        # almost every small input fit in its entirety, missing heap evictions.
        width=rng.randint(1,n);start=rng.randint(0,n-width)
        threshold=max(charges[start:start+width])+width*sum(costs[start:start+width])
        return {'chargeTimes':charges,'runningCosts':costs,
                'budget':rng.choice([1,10**15,max(1,threshold+rng.choice([-1,0,1]))])}
    if qid == 2580:
        if rng.randrange(3)==0:
            offset=rng.choice([0,1000000000-2*n]) if edge else 0
            return {'ranges':[[offset+2*i,offset+2*i] for i in range(n)]}
        return {'ranges':[sorted([rng.randint(0,40),rng.randint(0,40)]) for _ in range(n)]}
    if qid == 2597:return {'nums':[pick(1000) for _ in range(min(n,18))],'k':pick(1000)}
    if qid == 2438:
        value=rng.choice([1,2,15,1000000000]) if edge else rng.randint(1,1000000000)
        limit=value.bit_count()
        return {'n':value,'queries':[sorted([rng.randrange(limit),rng.randrange(limit)]) for _ in range(n)]}
    if qid == 2537:return {'nums':[pick(1000000000) for _ in range(n)],'k':pick(1000000000)}
    if qid == 2588:return {'nums':[rng.choice([0,1,524288,1000000]) if edge else rng.randrange(31) for _ in range(n)]}
    if qid == 2616:return {'nums':[pick(1000000000)-1 for _ in range(min(n,12))],
                          'p':rng.randrange(min(n,12)//2+1)}
    raise ValueError('unsupported routed generator')
