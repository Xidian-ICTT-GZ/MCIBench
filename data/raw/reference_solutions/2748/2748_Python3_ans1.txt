class Solution:
    def countBeautifulPairs(self, nums: List[int]) -> int:
        n = len(nums)
        res = 0
        for i in range(n):
            while nums[i] >= 10:
                nums[i] //= 10
            for j in range(i + 1, n):
                if gcd(nums[i] , nums[j] % 10) == 1:
                    res += 1
        return res