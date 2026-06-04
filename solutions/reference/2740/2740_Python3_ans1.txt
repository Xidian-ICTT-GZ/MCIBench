class Solution:
    def findValueOfPartition(self, nums: List[int]) -> int:
        nums.sort()
        res = inf
        for i in range(1, len(nums)):
            res = min(res, nums[i] - nums[i - 1])
        return res