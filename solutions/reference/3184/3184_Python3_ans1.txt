class Solution:
    def countCompleteDayPairs(self, hours: List[int]) -> int:
        ans = 0
        for i in range(1, len(hours)):
            for j in range(i):
                if (hours[i] + hours[j]) % 24 == 0:
                    ans += 1
        return ans