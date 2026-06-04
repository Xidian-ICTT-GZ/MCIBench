class Solution:
    def maximumLength(self, nums: List[int], k: int) -> int:
        dp = defaultdict(lambda: [0] * (k + 1))
        zd = [0] * (k + 1)

        for v in nums:
            tmp = dp[v]
            for j in range(k + 1):
                tmp[j] += 1
                if j > 0:
                    tmp[j] = max(tmp[j], zd[j - 1] + 1)    
            for j in range(k + 1):
                zd[j] = max(zd[j], tmp[j])
                if j > 0:
                    zd[j] = max(zd[j], zd[j - 1])
        
        return zd[k]