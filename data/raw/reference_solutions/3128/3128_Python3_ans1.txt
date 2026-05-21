class Solution:
    def numberOfRightTriangles(self, grid: List[List[int]]) -> int:
        n, m = len(grid), len(grid[0])
        col = [0] * m
        for j in range(m):
            for i in range(n):
                col[j] += grid[i][j]
        res = 0
        for i in range(n):
            row = sum(grid[i])
            for j in range(m):
                if grid[i][j] == 1:
                    res += (row - 1) * (col[j] - 1)
        return res