class Solution:
    def minFlips(self, grid: List[List[int]]) -> int:
        row_cnt, col_cnt = 0, 0
        m, n = len(grid), len(grid[0])
        for i in range(m):
            for j1 in range(n // 2):
                j2 = n - 1 - j1
                if grid[i][j1] != grid[i][j2]:
                    row_cnt += 1
        for j in range(n):
            for i1 in range(m // 2):
                i2 = m - 1 - i1
                if grid[i1][j] != grid[i2][j]:
                    col_cnt += 1
        return min(col_cnt, row_cnt)