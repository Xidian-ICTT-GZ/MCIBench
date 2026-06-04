class Solution:
    def modifiedMatrix(self, matrix: List[List[int]]) -> List[List[int]]:
        n, m = len(matrix), len(matrix[0])
        for j in range(m):
            zd = -1
            for i in range(n):
                zd = max(zd, matrix[i][j])
            for i in range(n):
                if matrix[i][j] == -1:
                    matrix[i][j] = zd
        return matrix