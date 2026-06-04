class Solution:
    def isPossibleToSplit(self, nums: List[int]) -> bool:
        count = {}
        for num in nums:
            count[num] = count.get(num, 0) + 1
            if count[num] > 2:
                return False
        return True