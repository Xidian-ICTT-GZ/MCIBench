class Solution:
    def splitNum(self, num: int) -> int:
        stnum = "".join(sorted(str(num)))
        num1, num2 = int(stnum[::2]), int(stnum[1::2])
        return num1 + num2