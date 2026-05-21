class Solution:
    def maximumNumberOfStringPairs(self, words: List[str]) -> int:
        ans = 0
        seen = set()
        for i, word in enumerate(words):
            if word[::-1] in seen:
                ans += 1
            seen.add(word)
        return ans