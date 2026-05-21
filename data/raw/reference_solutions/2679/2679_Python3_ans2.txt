class Solution:
    def matrixSum(self, nums: List[List[int]]) -> int:
        res = 0
        m = len(nums)
        n = len(nums[0])
        for i in range(m):
            nums[i].sort()
        for j in range(n):
            max_val = 0
            for i in range(m):
                max_val = max(max_val, nums[i][j])
            res += max_val
        return res