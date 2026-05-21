class Solution:
    def findPermutationDifference(self, s: str, t: str) -> int:
        char2index = {c: i for i, c in enumerate(s)}
        return sum(abs(i - char2index[c]) for i, c in enumerate(t))