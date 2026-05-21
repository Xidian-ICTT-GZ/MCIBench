class Solution:
    def maxHeightOfTriangle(self, red: int, blue: int) -> int:
        def maxHeight(x: int, y: int) -> int:
            odd = 2 * int(sqrt(x)) - 1
            even = 2 * int((-1 + sqrt(1 + 4 * y)) / 2)
            return min(odd, even) + 1
        
        return max(maxHeight(red, blue), maxHeight(blue, red))