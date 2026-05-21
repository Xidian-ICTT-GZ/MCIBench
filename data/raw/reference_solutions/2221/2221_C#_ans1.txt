public class Solution {
    public int TriangularSum(int[] nums) {
        List<int> current = new List<int>(nums);
        while (current.Count > 1) {
            List<int> newNums = new List<int>();
            for (int i = 0; i < current.Count - 1; ++i) {
                newNums.Add((current[i] + current[i + 1]) % 10);
            }
            current = newNums;
        }
        return current[0];
    }
}