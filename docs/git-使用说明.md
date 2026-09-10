# Git 日常操作速查

> 仓库：https://github.com/SOULC100/mahjong_bot
> 本文档只讲"每天怎么用"，不展开原理。

## 一句话理解

改动**不会**自动记录。只有你敲了 `git commit`，那一刻的代码才会被存成一个版本。

```
改代码 → git add → git commit → git push
         (暂存)     (本地存档)    (上传到 GitHub)
```

前两步离线完成，第三步才需要网络。

---

## 日常：改完代码，三步走

```powershell
git status                      # 1. 看看改了哪些文件
git save "说明这次改了什么"      # 2. 本地存档（= add + commit）
git push                        # 3. 上传到 GitHub
```

`git save` 是本仓库配好的别名，等价于 `git add -A && git commit -m "..."`。

### 更省事：双击 `commit.bat`

仓库根目录下的 `commit.bat` 把上面三步合成一步：

1. 双击 `commit.bat`（必须放在仓库根目录）
2. 它会先列出你改了哪些文件
3. 输入提交说明，回车
4. 自动完成 add + commit + push

也可以在命令行直接带上说明，跳过输入：

```powershell
commit.bat "fix: 修正听牌判断"
```

它会自动拦下两种情况：

- **没有改动** —— 不产生空提交，直接退出
- **凭据文件进入暂存区** —— 立即中止并撤销暂存（防止 token 被推上 GitHub）

> 该文件是 GBK + CRLF 编码，用编辑器另存为 UTF-8 后 cmd 里会显示乱码。

### 提交说明怎么写

一句话讲清"做了什么"，用中文就行：

```powershell
git save "feat: smart_bot 增加危险牌回避"
git save "fix: 修正七对向听计算错误"
git save "docs: 补充 API 说明"
git save "wip: 临时存档"
```

前缀（可选，但推荐）：`feat` 新功能 / `fix` 修 bug / `docs` 文档 / `test` 测试 / `wip` 半成品。

---

## 常见场景

### 只想提交部分文件

`git save` 是一把梭全部。想挑着提交就用原生命令：

```powershell
git add smart_bot.py tests/test_smart_bot.py   # 只暂存这两个
git commit -m "fix: 调整听牌判断"
git push
```

### 提交前先看改了什么

```powershell
git diff                        # 还没暂存的改动
git diff --cached               # 已经暂存、即将提交的改动
git status --short              # 只列文件名和状态
```

状态符号：`M` 已修改 / `A` 新增已暂存 / `??` 新文件未跟踪 / `D` 已删除

### 看历史

```powershell
git log --oneline               # 每条一行
git log --oneline -10           # 最近 10 条
git show <commit号>             # 看某次具体改了什么
```

### 改错了，想撤销

```powershell
# 撤销某个文件还没提交的改动（危险：改动直接丢失，无法找回）
git checkout -- smart_bot.py

# 撤销所有未提交的改动（更危险）
git checkout -- .

# 已经 commit 了但还没 push，想重新写说明
git commit --amend -m "新的说明"
```

⚠️ `git checkout --` 丢弃的改动**找不回来**，执行前先用 `git diff` 确认。

---

## 两条必须记住的规则

### 1. `data/` 永远不会被提交

`.gitignore` 里排除了 `data/`，里面的日志、回放 JSON，以及下面三个凭据文件都不进仓库：

- `data/tokens.txt`
- `data/xuanwu_token.txt`
- `data/portal_session.json`

所以 `git save` 不会泄露 token。但也意味着 **`data/` 没有版本备份**，重要数据要自己另外备份。

### 2. token 泄露是不可逆的

一旦 push 出去，即使之后删文件，凭据也会**永久留在 git 历史里**。

万一不小心提交了 token，处理顺序：

1. 立刻去麻将平台**重新生成 token**（作废旧的，这是唯一真正有效的补救）
2. 再把文件从仓库移除

---

## 出问题时

| 现象 | 原因 / 处理 |
|---|---|
| `nothing to commit` | 没有改动，正常 |
| `Your branch is ahead of 'origin/main' by N commits` | 有 N 次提交还没 push，敲 `git push` |
| `git save` 报路径错误 | 提交说明没用引号包起来，改成 `git save "有空格 的说明"` |
| `rejected - non-fast-forward` | 远程有你本地没有的提交，先 `git pull --rebase` 再 push |
| `Permission denied (publickey)` | SSH key 失效或换机器了，检查 `~/.ssh/id_ed25519` |

---

## 最简记忆版

```powershell
git status                  # 改了什么
git save "说明"             # 存下来
git push                    # 传上去
```

就这三条，覆盖 90% 的日常。
