class Solution:
    def winningPlayer(self, x: int, y: int) -> str:
        ops = min(x, y // 4)
        return "Alice" if ops % 2 == 1 else "Bob"