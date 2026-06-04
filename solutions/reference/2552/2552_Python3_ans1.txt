class Solution:
    def countQuadruplets(self, nums: List[int]) -> int:
        n = len(nums)
        pre = [0] * (n + 1)
        ans = 0
        for j in range(n):
            suf = 0
            for k in range(n - 1, j, -1):
                if nums[j] > nums[k]:
                    ans += pre[nums[k]] * suf
                else:
                    suf += 1
            for x in range(nums[j] + 1, n + 1):
                pre[x] += 1
        return ans