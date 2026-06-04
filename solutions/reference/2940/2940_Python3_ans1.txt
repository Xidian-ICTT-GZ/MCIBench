class Solution:
    def leftmostBuildingQueries(self, heights: List[int], queries: List[List[int]]) -> List[int]:
        n = len(heights)
        zd = [0] * (n * 4)

        def build(l, r, rt, heights):
            if l == r:
                zd[rt] = heights[l - 1]
                return

            mid = (l + r) // 2
            build(l, mid, rt << 1, heights)
            build(mid + 1, r, rt << 1 | 1, heights)
            zd[rt] = max(zd[rt << 1], zd[rt << 1 | 1])

        def query(pos, val, l, r, rt):
            if val >= zd[rt]:
                return 0
            if l == r:
                return l
            mid = (l + r) // 2
            if pos <= mid:
                res = query(pos, val, l, mid, rt << 1)
                if res != 0:
                    return res
            return query(pos, val, mid + 1, r, rt << 1 | 1)

        build(1, n, 1, heights)
        m = len(queries)
        ans = [0] * m
        for i in range(m):
            a, b = queries[i]
            if a > b:
                a, b = b, a
            if a == b or heights[a] < heights[b]:
                ans[i] = b
                continue
            ans[i] = query(b + 1, heights[a], 1, n, 1) - 1
        return ans