var uniquePathsWithObstacles = function(obstacleGrid) {
    const n = obstacleGrid.length, m = obstacleGrid[0].length;
    const f = new Array(m).fill(0);
    f[0] = obstacleGrid[0][0] === 0 ? 1 : 0;
    for (let i = 0; i < n; i++) {
        for (let j = 0; j < m; j++) {
            if (obstacleGrid[i][j] === 1) {
                f[j] = 0;
            } else if (j > 0 && obstacleGrid[i][j - 1] === 0) {
                f[j] += f[j - 1];
            }
        }
    }
    return f[m - 1];
};