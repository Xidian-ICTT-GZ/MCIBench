class Solution:
    def miceAndCheese(self, reward1: List[int], reward2: List[int], k: int) -> int:
        ans = 0
        n = len(reward1)
        diffs = [reward1[i] - reward2[i] for i in range(n)]
        ans += sum(reward2)
        diffs.sort()
        for i in range(1, k+1):
            ans += diffs[n - i]
        return ans