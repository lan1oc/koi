# Ideas System — 解题点子系统

## 概述

Ideas（解题点子）是 CTF Agent 的**运行时策略管理系统**。在解题过程中，辅助模型自动提炼"可以尝试的方向"，追踪每个方向的验证状态，形成一张**活的策略地图**。

它与 Skill 系统共同构成 Agent 的"大脑"：

| | **Skill（技能）** | **Ideas（点子）** |
|---|---|---|
| **本质** | 赛前知识库 | 赛中策略图 |
| **时间维度** | 静态、预先编写 | 动态、运行时生成 |
| **粒度** | 通用技术指南（如 SQL 注入攻略） | 针对当前题目的具体假设（如"试试登录页面的 SQL 注入"） |
| **生命周期** | 跨题目持久存在 | 绑定单个 Challenge |
| **作者** | 人类专家编写 | 辅助 AI 模型自动生成 |
| **价值** | 教 Agent "怎么打" | 告诉 Agent "当前这道题该试什么、别再试什么" |

## 核心设计思想

### 1. 点子是假设，不是记录

点子回答的是 **"接下来可以试什么方向？"**，而不是 "刚才做了什么"。

```
✅ GOOD Ideas:
  - "尝试对 /api/login 做 SQL 注入"
  - "检查 JWT token 的签名算法是否为 none"
  - "测试文件上传是否允许 .php 后缀"
  - "尝试利用 printf 的格式化字符串漏洞"

❌ BAD Ideas (这些不是点子):
  - "发现了 8080 端口开放"        → 这是观察/发现
  - "成功读取了 /etc/passwd"      → 这是执行结果
  - "下载了挑战文件"              → 这是具体任务
```

### 2. 状态驱动的策略演化

每个点子有明确的状态生命周期：

```
              ┌─────────┐
              │ pending  │ ← 新产生的假设
              │ (待验证)  │
              └────┬─────┘
                   │ Agent 开始尝试这个方向
                   ▼
              ┌─────────┐
              │ testing  │ ← 正在验证中
              │ (验证中)  │
              └────┬─────┘
                   │ 根据结果判定
          ┌────────┼────────┐
          ▼        ▼        ▼
     ┌─────────┐ ┌───────┐ ┌─────────┐
     │verified │ │failed │ │skipped  │
     │ (有效)   │ │(无效)  │ │(跳过)   │
     └─────────┘ └───────┘ └─────────┘
```

**关键理念：失败的点子和成功的点子一样有价值。**

一个被标记为 `failed` 的点子 + 失败原因，直接防止 Agent 在后续轮次中重复尝试同一方向。这在长时间解题（100+ 轮）中极其关键。

### 3. 辅助模型独立管理

点子由**辅助模型**（Utility Model）管理，与主解题模型分离：

```
┌──────────────────────────────────────────────┐
│                 主模型 (Main Agent)            │
│  职责: 解题、执行工具、分析结果               │
│  工具: bash, read_file, http_request, ...    │
│  不直接操作 ideas                             │
└──────────────┬───────────────────────────────┘
               │ 每 2 轮提供工具调用摘要
               ▼
┌──────────────────────────────────────────────┐
│              辅助模型 (Utility Model)          │
│  职责: 分析进展 → 提炼新点子 + 更新点子状态    │
│  输入: 工具调用日志 + 现有点子列表             │
│  输出: JSON { ideas, idea_updates }          │
│  异步执行，不阻塞主循环                       │
└──────────────────────────────────────────────┘
```

**为什么分离？**
- 主模型专注解题，不浪费 token 在元认知任务上
- 辅助模型可以用更轻量的模型（如 GPT-4o-mini），降低成本
- 避免主模型"当局者迷"——由旁观者做策略分析更客观

## 数据模型

```sql
CREATE TABLE challenge_ideas (
    id           TEXT PRIMARY KEY,       -- UUID
    challenge_id TEXT NOT NULL,          -- 关联的挑战 ID
    content      TEXT NOT NULL,          -- 点子内容 (≤100字)
    status       TEXT DEFAULT 'pending', -- pending/testing/verified/failed/skipped
    result       TEXT DEFAULT '',        -- 验证结果简述
    created_at   TIMESTAMP,
    updated_at   TIMESTAMP
);
```

## 与 Skill 系统的协作

Skill 和 Ideas 不是替代关系，而是**前后衔接**：

```
[解题开始]
    │
    ▼
┌─────────────────────┐
│ 1. 读取 Skill       │  ← read_skill("SQL Injection")
│    获取通用攻略       │     "SQL 注入的一般方法论..."
└──────────┬──────────┘
           │ Skill 提供了方法论
           ▼
┌─────────────────────┐
│ 2. 生成 Ideas       │  ← 辅助模型基于 Skill + 题目信息
│    具体化假设         │     "尝试对 /login 的 username 参数做 SQL 注入"
└──────────┬──────────┘
           │ Agent 执行 + 辅助模型更新状态
           ▼
┌─────────────────────┐
│ 3. Ideas 演化       │  ← "SQL 注入在 /login 失败(有 WAF)"
│    产生新假设         │     "尝试用 Unicode 编码绕过 WAF"
└──────────┬──────────┘
           │ 持续循环直到解题成功
           ▼
        [FLAG!]
```

## 未来发展方向

### 1. 跨题目知识迁移（Ideas → Lessons → Skills）

当前 Ideas 绑定单个 Challenge，但失败/成功的经验可以沉淀：

```
Ideas (运行时)                Lessons (赛后)              Skills (永久)
"尝试 SQL 注入 → failed"  →  "该平台有 WAF 防 SQLi"  →  更新 SQL 注入 Skill:
"Unicode 绕过 WAF → ok"      "Unicode 编码可绕过"        "遇到 WAF 时尝试 Unicode 编码"
```

**自动经验提炼**：解题完成后，从 verified/failed Ideas 中自动生成 Lessons，再由人工审核后合并入 Skill 库。形成 **Ideas → Lessons → Skills** 的知识飞轮。

### 2. 点子优先级排序

不是所有点子都值得立即尝试。可以增加 `priority` 字段：

```json
{
  "content": "尝试 SSTI 注入",
  "priority": "high",     // 基于: 题目使用了 Jinja2 模板
  "confidence": 0.85,     // 辅助模型的信心度
  "estimated_effort": "low"  // 预估尝试成本
}
```

辅助模型根据题目信息、已有 Skill、失败历史综合判断优先级，Agent 优先尝试高优先级、低成本的点子。

### 3. 点子关联图谱

点子之间存在因果关系：

```
"检查 robots.txt" ──发现──→ "访问 /admin 后台"
                                  │
                            ──需要──→ "尝试默认密码 admin:admin"
                                  │
                            ──失败──→ "尝试 SQL 注入绕过登录"
```

构建点子的**依赖图**，可以让 Agent 理解"做 B 之前需要先做 A"，避免跳步。

### 4. 多 Agent 协作时的点子共享

在 Multi-Agent 架构中，不同子 Agent（Web Agent、Pwn Agent、Recon Agent）可以共享点子池：

```
Recon Agent: "发现 8443 端口运行 Flask 应用" (observation)
    ↓ 触发
Web Agent Ideas: "尝试 SSTI 注入 Flask/Jinja2"
    ↓ 验证失败
Web Agent Ideas: "尝试 Flask debug mode PIN 计算"
```

### 5. 人机协作

用户在前端 IdeasPanel 中可以：
- **手动添加点子**：把自己的灵感注入 Agent 策略
- **标记优先级**：告诉 Agent "先试这个"
- **否决点子**：标记为 skipped 防止 Agent 浪费时间
- **添加备注**：给 Agent 提供人类直觉

这让 CTF Agent 从"全自动"变为"人机协作"模式——人类提供直觉和创意，Agent 提供执行力和耐心。

### 6. 点子模板化

对于常见题型，可以预置"点子模板"：

```yaml
# ideas-templates/web.yaml
- trigger: "检测到 PHP 应用"
  ideas:
    - "检查是否存在 .git 源码泄露"
    - "测试 PHP 反序列化漏洞"
    - "尝试 PHP 伪协议读取源码"

- trigger: "检测到文件上传功能"
  ideas:
    - "测试上传 .php webshell"
    - "测试双扩展名绕过 (.php.jpg)"
    - "测试 Content-Type 绕过"
```

相当于**动态版 Skill**——根据运行时发现自动注入相关点子，而不是等 Agent 自己想到。

### 7. 统计与复盘

```
Challenge: Web-Login-Bypass
Duration: 45 rounds
Ideas generated: 12
  ✅ verified: 2 (17%)
  ❌ failed: 7 (58%)
  ⏭️ skipped: 1 (8%)
  ⏳ pending: 2 (17%)

Key insight: Agent 在 SQL 注入上花了 15 轮才放弃，
             如果点子系统更早标记 failed，可以节省 ~10 轮。

Winning path: robots.txt → /admin → SSTI → RCE → flag
```

这些统计数据可以反馈到 Skill 优化中，形成闭环。

## 总结

| 维度 | Skill | Ideas |
|------|-------|-------|
| **When** | 解题前 | 解题中 |
| **What** | 通用技术知识 | 针对当前题目的策略假设 |
| **Who** | 人类专家编写 | AI 辅助模型自动生成 |
| **Lifetime** | 永久 | 单次 Challenge |
| **Value** | 教 Agent 方法论 | 指导 Agent 当前决策、避免重复 |

**Skill 是 Agent 的"教科书"，Ideas 是 Agent 的"草稿纸"。**

一个只读教科书不做笔记的学生，和一个边学边思考、边试错边记录的学生，解题效率天差地别。Ideas 系统就是让 AI Agent 拥有"边做边想"的能力。
