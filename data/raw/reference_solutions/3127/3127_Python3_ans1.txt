class Solution:
    def canMakeSquare(self, grid: List[List[str]]) -> bool:
        for i in range(2):
            for j in range(2):
                if self.check(grid, i, j):
                    return True
        return False

    def check(self, grid: List[List[str]], x: int, y: int) -> bool:
        count = 0
        for i in range(2):
            for j in range(2):
                count += (grid[x + i][y + j] == 'B')
        return count != 2