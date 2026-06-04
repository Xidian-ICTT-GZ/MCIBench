class Solution:
    def numberOfPermutations(self, n: int, requirements: List[List[int]]) -> int:

        mod = 10 ** 9 + 7
        reqMap = {0: 0}
        for end, cnt in requirements:
            reqMap[end] = cnt
        if reqMap[0]:
            return 0
        
        @cache
        def dfs(end: int, cnt: int) -> int:
            if cnt < 0:
                return 0
            if end == 0:
                return 1
            if end - 1 in reqMap:
                r = reqMap[end - 1]
                if r <= cnt <= end + r:
                    return dfs(end - 1, r)
                else:
                    return 0
            else:
                if cnt > end:
                    return (dfs(end, cnt - 1) - dfs(end - 1, cnt - 1 - end) + dfs(end - 1, cnt)) % mod
                else:
                    return (dfs(end, cnt - 1) + dfs(end - 1, cnt)) % mod
        
        return dfs(n - 1, reqMap[n - 1])