class Solution:
    def buyChoco(self, prices: List[int], money: int) -> int:
        fi, se = inf, inf
        for price in prices:
            if price < fi:
                se, fi = fi, price
            elif price < se:
                se = price
        return money if money < fi + se else money - fi - se