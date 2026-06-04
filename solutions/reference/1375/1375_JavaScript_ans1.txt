var numTimesAllBlue = function(flips) {
    const n = flips.length;
    let ans = 0, right = 0;
    for (let i = 0; i < n; ++i) {
        right = Math.max(right, flips[i]);
        if (right === i + 1) {
            ++ans;
        }
    }
    return ans;
};