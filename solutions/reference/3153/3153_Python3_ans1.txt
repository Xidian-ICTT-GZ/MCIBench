class Solution:
    def sumDigitDifferences(self, nums: List[int]) -> int:
        res = 0
        n = len(nums)
        while nums[0] > 0:
            cnt = [0] * 10
            for i in range(n):
                cnt[nums[i] % 10] += 1
                nums[i] = nums[i] // 10
            for i in range(10):
                res += (n - cnt[i]) * cnt[i]
        return res // 2