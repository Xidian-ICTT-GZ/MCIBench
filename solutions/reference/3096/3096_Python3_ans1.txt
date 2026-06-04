class Solution:
    def minimumLevels(self, possible: List[int]) -> int:
        n = len(possible)
        tot = sum(possible) * 2 - n
        pre = 0
        for i in range(n - 1):
            pre += 1 if possible[i] == 1 else -1
            if 2 * pre > tot:
                return i + 1
        return -1