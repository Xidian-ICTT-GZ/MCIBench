class Solution:
    def minimumMoves(self, nums: List[int], k: int, maxChanges: int) -> int:
        n = len(nums)
        def f(i: int) -> int:
            return sum(nums[max(i - 1, 0):min(i + 2, n)])

        left, right = 0, -1
        leftSum, rightSum = 0, 0
        leftCount, rightCount = 0, 0
        res = inf
        for i in range(n):
            if f(i) + maxChanges >= k:
                if k <= f(i):
                    res = min(res, k - nums[i])
                else:
                    res = min(res, 2 * k - f(i) - nums[i])
            if k <= maxChanges:
                continue
            while right + 1 < n and (right - i < i - left or leftCount + rightCount + maxChanges < k):
                if nums[right + 1] == 1:
                    rightCount += 1
                    rightSum += right + 1
                right += 1
            while leftCount + rightCount + maxChanges > k:
                if right - i < i - left or right - i == i - left and nums[left] == 1:
                    if nums[left] == 1:
                        leftCount -= 1
                        leftSum -= left
                    left += 1
                else:
                    if nums[right] == 1:
                        rightCount -= 1
                        rightSum -= right
                    right -= 1
            res = min(res, leftCount * i - leftSum + rightSum - rightCount * i + 2 * maxChanges)
            if nums[i] == 1:
                leftCount += 1
                leftSum += i
                rightCount -= 1
                rightSum -= i
        return res