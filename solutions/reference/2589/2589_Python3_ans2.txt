class Solution:
    def findMinimumTime(self, tasks: List[List[int]]) -> int:
        res, m = 0, max(tasks, key = lambda task: task[1])[1]
        for i in range(1, m + 1):
            run = False
            for _, end, duration in tasks:
                if duration > 0 and end - i + 1 == duration:
                    run = True
            if run:
                for task in tasks:
                    if i >= task[0] and i <= task[1] and task[2] > 0:
                        task[2] -= 1
                res += 1
        return res