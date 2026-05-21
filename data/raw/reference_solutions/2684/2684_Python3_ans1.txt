class Solution:
    def maxMoves(self, grid: List[List[int]]) -> int:
        m, n = len(grid), len(grid[0])
        q = set(range(m))
        for j in range(1, n):
            q2 = set()
            for i in q:
                for i2 in [i - 1, i, i + 1]:
                    if 0 <= i2 < m and grid[i][j - 1] < grid[i2][j]:
                        q2.add(i2)
            q = q2
            if not q:
                return j - 1
        return n - 1