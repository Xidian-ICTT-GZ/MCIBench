class Solution:
    def beautifulSubarrays(self, nums: List[int]) -> int:
        cnt = {0: 1}
        mask = 0
        ans = 0
        for x in nums:
            mask ^= x
            ans += cnt.get(mask, 0)
            cnt[mask] = cnt.get(mask, 0) + 1
        return ans