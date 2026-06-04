class Solution:
    def numberOfPairs(self, nums1: List[int], nums2: List[int], k: int) -> int:
        count = Counter(nums1)
        max1 = max(count)
        res = 0
        for a, cnt in Counter(nums2).items():
            for b in range(a * k, max1 + 1, a * k):
                if b in count:
                    res += count[b] * cnt
        return res