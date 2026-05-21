class Solution:
    def isAcronym(self, words: List[str], s: str) -> bool:
        return len(words) == len(s) and all(words[i][0] == s[i] for i in range(len(s)))