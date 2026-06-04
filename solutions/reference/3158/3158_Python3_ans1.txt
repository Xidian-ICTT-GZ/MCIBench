class Solution:
    def duplicateNumbersXOR(self, nums: List[int]) -> int:
        cnt = set()
        res = 0    
        for num in nums:
            if num in cnt:
                res ^= num
            else:
                cnt.add(num)
        return res