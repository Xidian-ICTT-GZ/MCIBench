class Solution:
    def numberOfAlternatingGroups(self, colors: List[int]) -> int:
        n = len(colors)
        res = 0
        for i in range(n):
            if colors[i] != colors[i - 1] and colors[i] != colors[(i + 1) % n]:
                res += 1
        return res