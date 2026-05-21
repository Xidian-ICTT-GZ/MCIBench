class Solution:
    def smallestString(self, s: str) -> str:
        indexOfFirstNonA = self.findFirstNonA(s)
        if indexOfFirstNonA == len(s):
            return s[:-1] + 'z'
        indexOfFirstA_AfterFirstNonA = self.findFirstA_AfterFirstNonA(s, indexOfFirstNonA)
        res = []
        for i, c in enumerate(s):
            if indexOfFirstNonA <= i < indexOfFirstA_AfterFirstNonA:
                res.append(chr(ord(c)-1))
            else:
                res.append(c)
        return ''.join(res)

    def findFirstNonA(self, s: str) -> int:
        for i, c in enumerate(s):
            if c != 'a':
                return i
        return len(s)

    def findFirstA_AfterFirstNonA(self, s:str, firstNonA: int) -> int:
        for i in range(firstNonA, len(s)):
            if s[i] == 'a':
                return i
        return len(s)