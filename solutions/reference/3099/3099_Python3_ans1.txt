class Solution:
    def sumOfTheDigitsOfHarshadNumber(self, x: int) -> int:
        s = 0
        y = x
        while y:
            y, r = divmod(y, 10)
            s += r
        return -1 if x % s else s