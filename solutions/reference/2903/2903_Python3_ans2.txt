class Solution:
    def findIndices(self, nums: List[int], indexDifference: int, valueDifference: int) -> List[int]:
        minIndex, maxIndex = 0, 0
        for j in range(indexDifference, len(nums)):
            i = j - indexDifference
            if nums[i] < nums[minIndex]:
                minIndex = i
            if nums[j] - nums[minIndex] >= valueDifference:
                return [minIndex, j]
            if nums[i] > nums[maxIndex]:
                maxIndex = i
            if nums[maxIndex] - nums[j] >= valueDifference:
                return [maxIndex, j]
        return [-1, -1]