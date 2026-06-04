class Solution:
    def maxScore(self, grid: List[List[int]]) -> int:
        m, n = len(grid), len(grid[0])
        precol = [-inf] * n
        ans = -inf

        for i in range(m):
            prerow = -inf
            for j in range(n):
                f = -inf
                if i > 0:
                    f = max(f, grid[i][j] + precol[j])
                if j > 0:
                    f = max(f, grid[i][j] + prerow)
                ans = max(ans, f)
                precol[j] = max(precol[j], max(f, 0) - grid[i][j])
                prerow = max(prerow, max(f, 0) - grid[i][j])
        
        return ans