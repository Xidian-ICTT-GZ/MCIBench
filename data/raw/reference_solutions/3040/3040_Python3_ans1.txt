class Solution:
    def maxOperations(self, nums: List[int]) -> int:
        n = len(nums)

        @cache
        def dfs(i, j, target):
            if i >= j:
                return 0
            ans = 0
            if nums[i] + nums[i + 1] == target:
                ans = max(ans, 1 + dfs(i + 2, j, target))
            if nums[i] + nums[j] == target:
                ans = max(ans, 1 + dfs(i + 1, j - 1, target))
            if nums[j - 1] + nums[j] == target:
                ans = max(ans, 1 + dfs(i , j - 2, target))
            return ans

        res = 0
        res = max(res, dfs(0, n - 1, nums[0] + nums[1]))
        res = max(res, dfs(0, n - 1, nums[0] + nums[n - 1]))
        res = max(res, dfs(0, n - 1, nums[n - 2] + nums[n - 1]))
        return res