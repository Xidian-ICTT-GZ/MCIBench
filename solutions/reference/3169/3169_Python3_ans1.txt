class Solution:
    def countDays(self, days: int, meetings: List[List[int]]) -> int:
        meetings.sort()
        l, r = 1, 0
        for m in meetings:
            if m[0] > r:
                days -= r - l + 1
                l = m[0]
            r = max(r, m[1])
        days -= r - l + 1
        return days