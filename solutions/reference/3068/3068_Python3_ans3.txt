class Solution:
    def maximumValueSum(self, nums: List[int], k: int, edges: List[List[int]]) -> int:
        f0, f1 = 0, -inf
        for x in nums:
            t = max(f1 + x, f0 + (x ^ k))
            f0, f1 = max(f0 + x, f1 + (x ^ k)), t
        return f0