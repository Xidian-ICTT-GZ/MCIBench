class Solution:
    def differenceOfSum(self, nums: List[int]) -> int:
        elementSum, digitSum = 0, 0
        for num in nums:
            elementSum += num
            while num > 0:
                digitSum += num % 10
                num //= 10
        return elementSum - digitSum