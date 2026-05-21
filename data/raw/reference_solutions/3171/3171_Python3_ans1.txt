class Solution:
    def minimumDifference(self, nums: List[int], k: int) -> int:
        n = len(nums)
        bits_max_pos = [-1] * 31
        res = inf
        
        for i in range(n):
            for j in range(31):
                if nums[i] >> j & 1:
                    bits_max_pos[j] = i
            pos_to_bit = [(bits_max_pos[j], j) for j in range(31) if bits_max_pos[j] != -1]
            pos_to_bit.sort(reverse = True, key = lambda x: x[0])
            
            j, val = 0, 0
            while j < len(pos_to_bit):
                p = j
                while j < len(pos_to_bit) and pos_to_bit[j][0] == pos_to_bit[p][0]:
                    val |= 1 << pos_to_bit[j][1]
                    j += 1
                res = min(res, abs(val - k))
        
        return res