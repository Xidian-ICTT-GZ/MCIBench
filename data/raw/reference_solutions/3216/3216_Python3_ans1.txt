class Solution:
    def getSmallestString(self, s: str) -> str:
        s = list(s)
        for i in range(0, len(s) - 1):
            if s[i] > s[i + 1] and ord(s[i]) % 2 == ord(s[i + 1]) % 2:
                s[i], s[i + 1] = s[i + 1], s[i]
                break
        return ''.join(s)