class Solution:
    def distinctDifferenceArray(self, nums: List[int]) -> List[int]:
        st = set()
        sufCnt = [0] * (len(nums) + 1)
        for i in range(len(nums) - 1, 0, -1):
            st.add(nums[i])
            sufCnt[i] = len(st)
        res = []
        st.clear()
        for i in range(len(nums)):
            st.add(nums[i])
            res.append(len(st) - sufCnt[i + 1])
        return res