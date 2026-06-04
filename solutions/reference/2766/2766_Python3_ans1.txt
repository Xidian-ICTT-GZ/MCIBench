class Solution:
    def relocateMarbles(self, nums: List[int], moveFrom: List[int], moveTo: List[int]) -> List[int]:
        mp = {}
        ans = []
        for num in nums:
            mp[num] = True
        for i in range(len(moveFrom)):
            if moveFrom[i] in mp:
                del mp[moveFrom[i]]
            mp[moveTo[i]] = True
        ans = list(mp.keys())
        ans.sort()
        return ans