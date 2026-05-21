class Solution:
    def beautifulSubsets(self, nums: List[int], k: int) -> int:
        ans = 0
        cnt = {}
        def dfs(i):
            nonlocal ans
            if i == len(nums):
                ans += 1
                return
            dfs(i + 1)
            if cnt.get(nums[i] - k, 0) == 0 and cnt.get(nums[i] + k, 0) == 0:
                cnt[nums[i]] = cnt.get(nums[i], 0) + 1
                dfs(i + 1)
                cnt[nums[i]] -= 1

        dfs(0)
        return ans - 1