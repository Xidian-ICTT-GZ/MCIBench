class Solution:
    def minimumAverage(self, nums: List[int]) -> float:
        nums.sort()
        res, n = inf, len(nums)
        for i in range(n // 2):
            res = min(res, (nums[i] + nums[n - 1 - i]) / 2)
        return res