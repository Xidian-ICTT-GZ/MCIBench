class Solution:
    def smallestBeautifulString(self, s: str, k: int) -> str:
        for i in range(len(s) - 1, -1, -1):
            blockedCharacters = set()
            for j in range(1, 3):
                if i - j >= 0:
                    blockedCharacters.add(s[i - j])
            for j in range(1, 4):
                if ord(s[i]) - ord('a') + j + 1 <= k and chr(ord(s[i]) + j) not in blockedCharacters:
                    return self.generate(s, i, j)
        return ""

    def generate(self, s: str, idx: str, offset: str) -> str:
        res = list(s)
        res[idx] = chr(ord(res[idx]) + offset)
        for i in range(idx + 1, len(s)):
            blockedCharacters = set()
            for j in range(1, 3):
                if i - j >= 0:
                    blockedCharacters.add(res[i - j])
            for j in range(3):
                if chr(ord('a') + j) not in blockedCharacters:
                    res[i] = chr(ord('a') + j)
                    break
        return ''.join(res)