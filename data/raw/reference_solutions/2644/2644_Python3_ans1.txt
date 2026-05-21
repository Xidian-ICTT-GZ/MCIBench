class Solution(object):
    def maxDivScore(self, nums, divisors):
        cnt, ans = -1, 0

        for i in range (0, len(divisors)):
            tmp = sum(1 for num in nums if num % divisors[i] == 0)
            if tmp > cnt or tmp == cnt and divisors[i] < ans:
                cnt = tmp
                ans = divisors[i]
        return ans;