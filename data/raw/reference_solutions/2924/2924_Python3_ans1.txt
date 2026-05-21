class Solution:
    def findChampion(self, n: int, edges: List[List[int]]) -> int:
        degree = [0] * n
        for x, y in edges:
            degree[y] += 1
        champion = -1
        for i, d in enumerate(degree):
            if d == 0:
                if champion == -1:
                    champion = i
                else:
                    return -1
        return champion