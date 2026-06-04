class Solution:
    def circularGameLosers(self, n: int, k: int) -> List[int]:
        visit = [False] * n
        i = k
        j = 0
        while not visit[j]:
            visit[j] = True
            j = (j + i) % n
            i += k
        ans = []
        for i in range(n):
            if not visit[i]:
                ans.append(i + 1)
        return ans