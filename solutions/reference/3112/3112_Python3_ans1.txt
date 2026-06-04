class Solution:
    def minimumTime(self, n: int, edges: List[List[int]], disappear: List[int]) -> List[int]:
        adj = [[] for _ in range(n)]
        for u, v, length in edges:
            adj[u].append([v, length])
            adj[v].append([u, length])
        pq = [[0, 0]]
        answer = [-1] * n
        answer[0] = 0
        while pq:
            t, u = heappop(pq)
            if t != answer[u]:
                continue
            for v, length in adj[u]:
                if t + length < disappear[v] and (answer[v] == -1 or t + length < answer[v]):
                    heappush(pq, [t + length, v])
                    answer[v] = t + length
        return answer