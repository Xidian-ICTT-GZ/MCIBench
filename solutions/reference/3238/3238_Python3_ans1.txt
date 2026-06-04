class Solution:
    def winningPlayerCount(self, n: int, pick: List[List[int]]) -> int:
        cnt = [[0] * 11 for _ in range(n)]
        for p in pick:
            cnt[p[0]][p[1]] += 1
        ans = 0
        for i, arr in enumerate(cnt):
            if any(x > i for x in arr):
                ans += 1
        return ans