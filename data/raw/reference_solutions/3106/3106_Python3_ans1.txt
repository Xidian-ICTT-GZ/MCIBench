class Solution:
    def getSmallestString(self, s: str, k: int) -> str:
        ans = list(s)
        for i, ch in enumerate(s):
            dis = min(ord(s[i]) - ord('a'), ord('z') - ord(s[i]) + 1)
            if dis <= k:
                ans[i] = 'a'
                k -= dis
            else:
                ans[i] = chr(ord(ans[i]) - k)
                break
        return "".join(ans)