class Solution:
    def findWinningPlayer(self, skills: List[int], k: int) -> int:
        n = len(skills)
        cnt = 0
        i, last_i = 0, 0
        while i < n:
            j = i + 1
            while j < n and skills[j] < skills[i] and cnt < k:
                cnt += 1
                j += 1
            if cnt == k:
                return i
            cnt = 1
            last_i = i
            i = j
        return last_i