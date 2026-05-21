class Solution:
    def sumIndicesWithKSetBits(self, nums: List[int], k: int) -> int:
        def bitCount(x: int) -> int:
            x = (x & 0b0101010101) + ((x & 0b1010101010) >> 1)
            x = ((x & 0b0011001100) >> 2) + (x & 0b1100110011)
            x = (x >> 8) + ((x >> 4) & 0b1111) + (x & 0b1111)
            return x
        
        ans = 0
        for i, num in enumerate(nums):
            if bitCount(i) == k:
                ans += num
        return ans