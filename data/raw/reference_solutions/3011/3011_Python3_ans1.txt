class Solution:
    def canSortArray(self, nums: List[int]) -> bool:
        lastCnt = 0
        lastGroupMax = 0
        curGroupMax = 0
        for num in nums:
            curCnt = num.bit_count()
            if curCnt == lastCnt:
                curGroupMax = max(curGroupMax, num)
            else:
                lastCnt = curCnt
                lastGroupMax = curGroupMax
                curGroupMax = num
            if num < lastGroupMax:
                return False
        return True