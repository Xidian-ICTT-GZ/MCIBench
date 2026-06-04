class Solution:
    def minimumCost(self, m: int, n: int, H: List[int], V: List[int]) -> int:  
        H.sort(), V.sort()
        h, v = 1, 1
        res = 0
        while H or V:
            if not V or (H and H[-1] > V[-1]):
                res += H.pop() * h
                v += 1
            else:
                res += V.pop() * v
                h += 1
        return res