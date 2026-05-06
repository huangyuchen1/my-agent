---
name: git
description: Git workflow helpers - commit conventions, branching strategy, PR guidelines
---

# Git Workflow Skill

## Commit Message Format

遵循 Conventional Commits 规范：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**类型 (type)**:
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档变更
- `style`: 代码格式（不影响功能）
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具变更

**示例**:
```
feat(auth): add OAuth2 login support

- Implement Google OAuth2 flow
- Add user profile sync
- Handle token refresh

Closes #123
```

## Branch Strategy

- `main` / `master`: 生产环境，只接受 PR 合并
- `develop`: 开发主分支
- `feature/<name>`: 功能分支
- `fix/<name>`: 修复分支
- `hotfix/<name>`: 紧急修复

**命名规范**:
- 使用 kebab-case: `feature/user-auth`
- 关联 Issue: `feature/123-add-login`

## Pull Request 流程

1. **创建分支**: `git checkout -b feature/xxx`
2. **频繁提交**: 每次完成小功能就提交
3. **保持 Rebase**: 定期 rebase 到主分支
4. **描述清晰**: PR 包含:
   - 解决的问题/添加的功能
   - 技术方案
   - 测试计划
5. **Code Review**: 至少 1 人 review 后合并

## 常用命令

```bash
# 创建并切换
git checkout -b feature/xxx

# 查看状态
git status

# 添加更改
git add -p  # 交互式添加

# 提交
git commit -m "feat(scope): description"

# 推送
git push -u origin feature/xxx

# 更新主分支
git fetch origin
git rebase origin/main

# 合并 PR
git checkout main
git merge feature/xxx
git push origin main

# 查看历史
git log --oneline --graph
```
