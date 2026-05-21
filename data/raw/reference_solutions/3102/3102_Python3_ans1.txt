from sortedcontainers import SortedList

class Solution:
    def minimumDistance(self, points: List[List[int]]) -> int:
        sx = SortedList(p[0] - p[1] for p in points)
        sy = SortedList(p[0] + p[1] for p in points)
        res = float('inf')
        for p in points:
            sx.remove(p[0] - p[1])
            sy.remove(p[0] + p[1])
            res = min(res, max(sx[-1] - sx[0], sy[-1] - sy[0]))
            sx.add(p[0] - p[1])
            sy.add(p[0] + p[1])
        return res