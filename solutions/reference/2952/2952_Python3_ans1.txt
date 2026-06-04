class Solution:
    def minimumAddedCoins(self, coins: List[int], target: int) -> int:
        coins.sort()
        ans, x = 0, 1
        length, index = len(coins), 0

        while x <= target:
            if index < length and coins[index] <= x:
                x += coins[index]
                index += 1
            else:
                x <<= 1
                ans += 1
        
        return ans