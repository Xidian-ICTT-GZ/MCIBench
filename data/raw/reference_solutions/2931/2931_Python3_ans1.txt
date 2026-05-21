class Solution:
    def maxSpending(self, values: List[List[int]]) -> int:
        m, n = len(values), len(values[0])
        q = [(values[i][-1], i, n - 1) for i in range(m)]
        heapify(q)
        ans = 0
        for turn in range(1, m * n + 1):
            val, i, j = heappop(q)
            ans += val * turn
            if j > 0:
                heappush(q, (values[i][j - 1], i, j - 1))
        return ans