class Solution:
    def maxNumOfMarkedIndices(self, nums: List[int]) -> int:
        nums.sort()
        n = len(nums)
        m = n // 2
        res = 0
        i, j = 0, m
        while i < m and j < n:
            while j < n and 2 * nums[i] > nums[j]:
                j += 1
            if j < n:
                res += 2
                j += 1
            i += 1
        return res