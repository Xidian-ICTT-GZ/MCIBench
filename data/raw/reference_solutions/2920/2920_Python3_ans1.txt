class Solution:
    def maximumPoints(self, edges: List[List[int]], coins: List[int], k: int) -> int:
        n = len(coins)
        children = [[] for _ in range(n)]
        for u, v in edges:
            children[u].append(v)
            children[v].append(u)

        @cache
        def dfs(node, parent, f):
            res0 = (coins[node] >> f) - k
            res1 = coins[node] >> (f + 1) if f + 1 < 14 else 0
            for child in children[node]:
                if child == parent:
                    continue
                res0 += dfs(child, node, f)
                if f + 1 < 14:
                    res1 += dfs(child, node, f + 1)
            return max(res0, res1)

        return dfs(0, -1, 0)