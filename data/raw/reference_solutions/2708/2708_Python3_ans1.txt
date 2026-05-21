class Solution:
    def maxStrength(self, nums: List[int]) -> int:
        negativeCount, zeroCount, positiveCount = 0, 0, 0
        prod = 1
        maxNegative = -9
        for num in nums:
            if num < 0:
                negativeCount += 1
                prod *= num
                maxNegative = max(maxNegative, num)
            elif num == 0:
                zeroCount += 1
            else:
                prod *= num
                positiveCount += 1
        if negativeCount == 1 and zeroCount == 0 and positiveCount == 0:
            return nums[0]
        if negativeCount <= 1 and positiveCount == 0:
            return 0
        if prod < 0:
            return prod // maxNegative
        else:
            return prod