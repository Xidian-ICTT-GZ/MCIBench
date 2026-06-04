class Solution:
    def maxScore(self, nums: List[int], x: int) -> int:
        res = nums[0]
        dp = [-inf, -inf]
        dp[nums[0] % 2] = nums[0]
        for i in range(1, len(nums)):
            parity = nums[i] % 2
            cur = max(dp[parity] + nums[i], dp[1 - parity] - x + nums[i])
            res = max(res, cur)
            dp[parity] = max(dp[parity], cur)
        return res