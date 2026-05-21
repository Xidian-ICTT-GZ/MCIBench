class Solution:
    def maximumLength(self, s: str) -> int:
        ans = -1

        chs = [[] for _ in range(26)]
        cnt = 0
        for i in range(len(s)):
            cnt += 1
            if i + 1 == len(s) or s[i] != s[i + 1]:
                ch = ord(s[i]) - ord('a')
                chs[ch].append(cnt)
                cnt = 0
                for j in range(len(chs[ch]) - 1, 0, -1):
                    if chs[ch][j] > chs[ch][j - 1]:
                        chs[ch][j], chs[ch][j - 1] = chs[ch][j - 1], chs[ch][j]
                    else:
                        break
                if len(chs[ch]) > 3:
                    chs[ch].pop()

        for i in range(26):
            if len(chs[i]) > 0 and chs[i][0] > 2:
                ans = max(ans, chs[i][0] - 2)
            if len(chs[i]) > 1 and chs[i][0] > 1:
                ans = max(ans, min(chs[i][0] - 1, chs[i][1]))
            if len(chs[i]) > 2:
                ans = max(ans, chs[i][2])

        return ans