class Solution:
    def maxTotalReward(self, rewardValues: List[int]) -> int:
        rewardValues.sort()
        m = rewardValues[-1]
        dp = [0] * (2 * m)
        dp[0] = 1
        for x in rewardValues:
            for k in range(2 * x - 1, x - 1, -1):
                if dp[k - x] == 1:
                    dp[k] = 1
        res = 0
        for i in range(len(dp)):
            if dp[i] == 1:
                res = i
        return res