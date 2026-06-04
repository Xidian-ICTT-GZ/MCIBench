class Solution:
    def findMaximumNumber(self, k: int, x: int) -> int:
        l, r = 1, (k + 1) << x
        while l < r:
            m = (l + r + 1) // 2
            if self.accumulatedPrice(x, m) > k:
                r = m - 1
            else:
                l = m
        return l

    def accumulatedPrice(self, x: int, num: int) -> int:
        res = 0
        length = len(bin(num)) - 2
        for i in range(x, length + 1, x):
            res += self.accumulatedBitPrice(i, num)
        return res

    def accumulatedBitPrice(self, x: int, num: int) -> int:
        period = 1 << x
        res = (period // 2) * (num // period)
        if num % period >= (period // 2):
            res += num % period - ((period // 2) - 1)
        return res