class Solution:
    def findMatrix(self, nums: List[int]) -> List[List[int]]:
        cnt = Counter(nums)
        ans = []
        
        while cnt:
            arr = []
            for key in list(cnt.keys()):
                cnt[key] -= 1
                arr.append(key)
                if cnt[key] == 0:
                    del cnt[key]
            ans.append(arr)
        
        return ans