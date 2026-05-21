class Solution:
    def canReach(self, arr: List[int], start: int) -> bool:
        if arr[start] == 0:
            return True

        n = len(arr)
        used = {start}
        q = collections.deque([start])

        while len(q) > 0:
            u = q.popleft()
            for v in [u + arr[u], u - arr[u]]:
                if 0 <= v < n and v not in used:
                    if arr[v] == 0:
                        return True
                    q.append(v)
                    used.add(v)
        
        return False