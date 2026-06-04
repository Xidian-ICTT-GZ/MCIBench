class Solution:
    def goodSubsetofBinaryMatrix(self, grid: List[List[int]]) -> List[int]:
        ans = []
        mp = {}
        m = len(grid)
        n = len(grid[0])

        for j in range(m):
            st = 0
            for i in range(n):
                st |= (grid[j][i] << i)
            mp[st] = j
        if 0 in mp:
            ans.append(mp[0])
            return ans
        for x, i in mp.items():
            for y, j in mp.items():
                if not (x & y):
                    return [min(i, j), max(i, j)]
        return ans