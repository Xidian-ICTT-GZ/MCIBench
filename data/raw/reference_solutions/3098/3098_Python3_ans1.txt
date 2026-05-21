class Solution:
    mod = int(1e9 + 7)
    inf = float('inf')

    def sumOfPowers(self, nums: List[int], k: int) -> int:
        n = len(nums)
        res = 0
        d = [[defaultdict(int) for _ in range(k + 1)] for _ in range(n)]
        nums.sort()

        for i in range(n):
            d[i][1][self.inf] = 1
            for j in range(i):
                diff = abs(nums[i] - nums[j])
                for p in range(2, k + 1):
                    for v, cnt in d[j][p - 1].items():
                        d[i][p][min(diff, v)] = (d[i][p][min(diff, v)] + cnt) % self.mod

            for v, cnt in d[i][k].items():
                res = (res + v * cnt % self.mod) % self.mod

        return res