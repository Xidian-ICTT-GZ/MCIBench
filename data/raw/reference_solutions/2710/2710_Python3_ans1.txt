class Solution:
    def removeTrailingZeros(self, num: str) -> str:
        n = len(num)
        while n > 0 and num[n - 1] == '0':
            n -= 1
        return num[0 : n]