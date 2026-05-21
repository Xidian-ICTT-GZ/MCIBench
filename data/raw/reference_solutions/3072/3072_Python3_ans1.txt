class BinaryIndexedTree:
    def __init__(self, n):
        self.val = [0] * n

    def add(self, i):
        while i < len(self.val):
            self.val[i] += 1
            i += i & -i

    def get(self, i):
        res = 0
        while i > 0:
            res += self.val[i]
            i &= i - 1
        return res

class Solution:
    def resultArray(self, nums: List[int]) -> List[int]:
        n = len(nums)
        sorted_nums = sorted(nums)
        index = {}
        for i,a in enumerate(sorted_nums):
            index[a] = i + 1
        arr1 = [nums[0]]
        arr2 = [nums[1]]
        tree1 = BinaryIndexedTree(n + 1)
        tree2 = BinaryIndexedTree(n + 1)
        tree1.add(index[nums[0]])
        tree2.add(index[nums[1]])
        for i in range(2, n):
            count1 = len(arr1) - tree1.get(index[nums[i]])
            count2 = len(arr2) - tree2.get(index[nums[i]])
            if count1 > count2 or count1 == count2 and len(arr1) <= len(arr2):
                arr1.append(nums[i])
                tree1.add(index[nums[i]])
            else:
                arr2.append(nums[i])
                tree2.add(index[nums[i]])
        return arr1 + arr2