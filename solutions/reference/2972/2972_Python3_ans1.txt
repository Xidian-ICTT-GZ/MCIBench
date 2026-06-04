class Solution:
    def incremovableSubarrayCount(self, nums: List[int]) -> int:
        ans = 0
        l = 0

        while l < len(nums) - 1:
            if nums[l] >= nums[l + 1]:
                break
            l += 1
        if l == len(nums) - 1:
            return 1 * len(nums) * (len(nums) + 1) // 2

        ans += l + 2
        for r in range(len(nums) - 1, 0, -1):
            if r < len(nums) - 1 and nums[r] >= nums[r + 1]:
                break
            while l >= 0 and nums[l] >= nums[r]:
                l -= 1
            ans += l + 2
        return ans