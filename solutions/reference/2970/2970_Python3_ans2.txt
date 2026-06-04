class Solution:
    def incremovableSubarrayCount(self, nums: List[int]) -> int:
        n = len(nums)
        res = 0
        l = 1
        while l < n and nums[l - 1] < nums[l]:
            l += 1
        res += l + (l < n)        
        for r in range(n - 2, -1, -1):
            while l > 0 and nums[l - 1] >= nums[r + 1]:
                l -= 1
            res += l + (l <= r)
            if nums[r] >= nums[r + 1]:
                break
        return res