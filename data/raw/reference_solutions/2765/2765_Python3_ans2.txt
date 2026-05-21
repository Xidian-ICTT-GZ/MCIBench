class Solution:
    def alternatingSubarray(self, nums: List[int]) -> int:
        res = -1
        firstIndex = 0
        for i in range(1, len(nums)):
            length = i - firstIndex + 1
            if nums[i] - nums[firstIndex] == (length - 1) % 2:
                res = max(res, length)
            else:
                if nums[i] - nums[i - 1] == 1:
                    firstIndex = i - 1
                    res = max(res, 2)
                else:
                    firstIndex = i
        return res