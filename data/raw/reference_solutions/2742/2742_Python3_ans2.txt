class Solution:
    def paintWalls(self, cost: List[int], time: List[int]) -> int:
        n = len(cost)
        f = [0] + [inf] * (n + 1)
        for (cost_i, time_i) in zip(cost, time):
            for j in range(n + 1, -1, -1):
                f[min(j + time_i, n) + 1] = min(f[min(j + time_i, n) + 1], f[j] + cost_i)
        return min(f[n], f[n + 1])