class Solution:
    def minimumValueSum(self, nums: List[int], andValues: List[int]) -> int:
        inf = (1 << 20) - 1

        @cache
        def dfs(i, j, cur):
            if i == len(nums) and j == len(andValues):
                return 0
            if i == len(nums) or j == len(andValues):
                return inf
            cur &= nums[i]
            if cur & andValues[j] < andValues[j]:
                return inf
            res = dfs(i + 1, j, cur)
            if cur == andValues[j]:
                res = min(res, dfs(i + 1, j + 1, inf) + nums[i])
            return res

        res = dfs(0, 0, inf)
        return res if res < inf else -1