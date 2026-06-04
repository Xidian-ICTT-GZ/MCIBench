class Solution:
    def occurrencesOfElement(self, nums: List[int], queries: List[int], x: int) -> List[int]:
        indices = [i for i, num in enumerate(nums) if num == x]
        return [-1 if len(indices) < q else indices[q - 1] for q in queries]