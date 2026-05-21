struct TreeNode* deleteNode(struct TreeNode* root, int key){
    struct TreeNode *cur = root, *curParent = NULL;
    while (cur && cur->val != key) {
        curParent = cur;
        if (cur->val > key) {
            cur = cur->left;
        } else {
            cur = cur->right;
        }
    }
    if (!cur) {
        return root;
    }
    if (!cur->left && !cur->right) {
        cur = NULL;
    } else if (!cur->right) {
        cur = cur->left;
    } else if (!cur->left) {
        cur = cur->right;
    } else {
        struct TreeNode *successor = cur->right, *successorParent = cur;
        while (successor->left) {
            successorParent = successor;
            successor = successor->left;
        }
        if (successorParent->val == cur->val) {
            successorParent->right = successor->right;
        } else {
            successorParent->left = successor->right;
        }
        successor->right = cur->right;
        successor->left = cur->left;
        cur = successor;
    }
    if (!curParent) {
        return cur;
    } else {
        if (curParent->left && curParent->left->val == key) {
            curParent->left = cur;
        } else {
            curParent->right = cur;
        }
        return root;
    }
}