class Solution:
    def minimizeMax(self, nums: List[int], p: int) -> int:
        nums.sort()

        def check(mx: int) -> bool:
            cnt = 0
            i = 0
            while i < len(nums) - 1:
                if nums[i + 1] - nums[i] <= mx:
                    cnt += 1
                    i += 2
                else:
                    i += 1
            return cnt >= p

        left, right = 0, nums[-1] - nums[0]
        while left < right:
            mid = (left + right) // 2
            if check(mid):
                right = mid
            else:
                left = mid + 1

        return left