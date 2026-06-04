class Solution:
    def minimumSubstringsInPartition(self, s: str) -> int:
        n = len(s)
        d = [inf] * (n + 1)
        occ_cnt = defaultdict(int)
        d[0] = 0
        for i in range(1, n + 1):
            occ_cnt.clear()
            max_cnt = 0
            for j in range(i, 0, -1):
                occ_cnt[s[j - 1]] += 1
                max_cnt = max(max_cnt, occ_cnt[s[j - 1]])
                if max_cnt * len(occ_cnt) == i - j + 1 and d[j - 1] != inf:
                    d[i] = min(d[i], d[j - 1] + 1)
        return d[n]