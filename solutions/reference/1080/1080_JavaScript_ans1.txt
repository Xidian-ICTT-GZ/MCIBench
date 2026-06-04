var sufficientSubset = function(root, limit) {
    const haveSufficient = checkSufficientLeaf(root, 0, limit);
    return haveSufficient ? root : null;
};

var checkSufficientLeaf = function(node, sum, limit) {
    if (node == null) {
        return false;
    }
    if (node.left == null && node.right == null) {
        return node.val + sum >= limit;
    }
    const haveSufficientLeft = checkSufficientLeaf(node.left, sum + node.val, limit);
    const haveSufficientRight = checkSufficientLeaf(node.right, sum + node.val, limit);
    if (!haveSufficientLeft) {
        node.left = null;
    }
    if (!haveSufficientRight) {
        node.right = null;
    }
    return haveSufficientLeft || haveSufficientRight;
};