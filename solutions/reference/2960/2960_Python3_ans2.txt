class Solution:
    def countTestedDevices(self, batteryPercentages: List[int]) -> int:
        need = 0
        for battery in batteryPercentages:
            if battery > need:
                need += 1
        return need