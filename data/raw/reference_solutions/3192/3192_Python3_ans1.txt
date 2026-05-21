class Solution:
    def minOperations(self, nums: List[int]) -> int:
        operation = 0
        for num in nums:
            if num == (operation % 2):
                operation += 1
        return operation