class Solution:
    def repairCars(self, ranks: List[int], cars: int) -> int:
        l , r = 1, ranks[0] * cars * cars
        def check(m: int) -> bool:
            return sum([floor(sqrt(m // x)) for x in ranks]) >= cars
        while l < r:
            m = l + r >> 1
            if check(m):
                r = m
            else:
                l = m + 1
        return l