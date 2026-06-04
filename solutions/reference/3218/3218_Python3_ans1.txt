class Solution:
    def minimumCost(self, m: int, n: int, horizontalCut: List[int], verticalCut: List[int]) -> int:
        
        @cache
        def dp(row1: int, col1: int, row2: int, col2: int) -> int:
            if row1 == row2 and col1 == col2:
                return 0
            res = inf
            for i in range(row1, row2):
                res = min(res, dp(row1, col1, i, col2) + dp(i + 1, col1, row2, col2) + horizontalCut[i])
            for i in range(col1, col2):
                res = min(res, dp(row1, col1, row2, i) + dp(row1, i + 1, row2, col2) + verticalCut[i])
            return res

        return dp(0, 0, m - 1, n - 1)