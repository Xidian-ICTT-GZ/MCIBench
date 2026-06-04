class Solution:
    def maximizeSum(self, nums: List[int], k: int) -> int:
        return (2 * max(nums) + k - 1) * k // 2