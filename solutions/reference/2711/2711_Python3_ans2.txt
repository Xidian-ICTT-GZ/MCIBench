class Solution:
    def differenceOfDistinctValues(self, grid: List[List[int]]) -> List[List[int]]:
        m, n = len(grid), len(grid[0])
        res = [[0] * n for i in range(m)]
        for i in range(m):
            x, y = i, 0
            s = set()
            while x < m and y < n:
                res[x][y] += len(s)
                s.add(grid[x][y])
                x += 1
                y += 1
        for j in range(1, n):
            x, y = 0, j
            s = set()
            while x < m and y < n:
                res[x][y] += len(s)
                s.add(grid[x][y])
                x += 1
                y += 1
        for i in range(m):
            x, y = i, n - 1
            s = set()
            while x >= 0 and y >= 0:
                res[x][y] -= len(s)
                res[x][y] = abs(res[x][y])
                s.add(grid[x][y])
                x -= 1
                y -= 1
        for j in range(n - 1):
            x, y = m - 1, j
            s = set()
            while x >= 0 and y >= 0:
                res[x][y] -= len(s)
                res[x][y] = abs(res[x][y])
                s.add(grid[x][y])
                x -= 1
                y -= 1
        return res