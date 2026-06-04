class Solution:
    def waysToReachStair(self, k: int) -> int:
        n, npow, ans = 0, 1, 0
        while True:
            if npow - n - 1 <= k <= npow:
                ans += comb(n + 1, npow - k)
            elif npow - n - 1 > k:
                break
            n += 1
            npow *= 2
        return ans