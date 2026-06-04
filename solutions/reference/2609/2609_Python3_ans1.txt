class Solution:
    def findTheLongestBalancedSubstring(self, s: str) -> int:
        res = 0
        n = len(s)
        count = [0, 0]
        for i in range(n):
            if s[i] == '1':
                count[1] += 1
                res = max(res, 2 * min(count))
            elif i == 0 or s[i-1] == '1':
                count[0] = 1
                count[1] = 0
            else:
                count[0] += 1
        return res