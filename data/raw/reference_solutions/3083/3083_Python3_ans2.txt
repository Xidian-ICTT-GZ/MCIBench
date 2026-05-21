class Solution:
    def isSubstringPresent(self, s: str) -> bool:
        h = [0] * 26
        for i in range(len(s) - 1):
            x = ord(s[i]) - ord('a')
            y = ord(s[i + 1]) - ord('a')
            h[x] |= 1 << y
            if h[y] >> x & 1:
                return True
        return False