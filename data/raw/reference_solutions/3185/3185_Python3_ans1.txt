class Solution:
    def countCompleteDayPairs(self, hours: List[int]) -> int:
        ans = 0
        cnt = [0] * 24
        for hour in hours:
            ans += cnt[(24 - hour % 24) % 24]
            cnt[hour % 24] += 1
        return ans