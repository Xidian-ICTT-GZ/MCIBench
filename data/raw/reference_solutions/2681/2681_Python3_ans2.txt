class Solution:
    def sumOfPower(self, nums: List[int]) -> int:
        nums.sort()
        dp, pre_sum = 0, 0
        res, mod = 0, 10 ** 9 + 7
        for i in range(len(nums)):
            dp = (nums[i] + pre_sum) % mod
            pre_sum = (pre_sum + dp) % mod
            res = (res + nums[i] * nums[i] * dp) % mod
        return res