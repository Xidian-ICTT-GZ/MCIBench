var maxSumDivThree = function(nums) {
    let f = [0, Number.MIN_SAFE_INTEGER, Number.MIN_SAFE_INTEGER];
    for (const num of nums) {
        const g = [...f];
        for (let i = 0; i < 3; ++i) {
            g[(i + num % 3) % 3] = Math.max(g[(i + num % 3) % 3], f[i] + num);
        }
        f = g;
    }
    return f[0];
};