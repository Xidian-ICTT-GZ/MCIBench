class Solution:
    def vowelStrings(self, words: List[str], left: int, right: int) -> int:
        vowels = set("aeiou")
        ans = 0
        for i in range(left, right + 1):
            word = words[i]
            if word[0] in vowels and word[-1] in vowels:
                ans += 1
        return ans