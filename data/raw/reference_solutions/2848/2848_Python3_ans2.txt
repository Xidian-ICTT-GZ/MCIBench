class Solution:
    def numberOfPoints(self, nums: List[List[int]]) -> int:
        C = max(y for _, y in nums)
        diff = [0] * (C + 2)
        for x, y in nums:
            diff[x] += 1
            diff[y + 1] -= 1
        
        ans = count = 0
        for i in range(1, C + 1):
            count += diff[i]
            if count > 0:
                ans += 1
        return ans