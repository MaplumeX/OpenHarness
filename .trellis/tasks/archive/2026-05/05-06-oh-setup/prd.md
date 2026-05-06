# 在 oh setup 中支持自定义提供商

## Goal

在 `oh setup` 交互流程中添加"自定义提供商"入口，让用户无需记忆 `oh provider add` 的众多参数，即可通过引导式交互完成任意 API 提供商的配置。

## What I already know

* `_configure_custom_profile_via_setup()` 已定义（cli.py:1450-1488），但从未被调用
* `oh setup` 当前流程：`_select_setup_workflow`（选 claude-api / openai-compatible）→ `_specialize_setup_target`（细化选择）→ `_ensure_profile_auth`（认证）→ 选模型 → 激活
* `oh provider add` 已作为非交互式替代方案存在（cli.py:1961-1996），需要 7+ 个必填 flag
* `_specialize_setup_target` 处理 claude-api / openai-compatible 两个分支的细化，但没有 custom 入口
* 默认 profile 目录（settings.py:181-259）定义了 9 个预设 profile，不包含 custom
* `setup_cmd` 接受可选 `profile` 参数，非交互模式下直接跳过选择器

## Assumptions (validated)

* "自定义提供商"作为 setup 工作流选择器的第三个选项出现（与 claude-api、openai-compatible 并列）
* `_configure_custom_profile_via_setup` 的现有逻辑基本可用，需小幅调整
* 不需要新增 ProviderProfile 字段
* 自定义 profile 创建后自动激活（与现有 setup 行为一致）

## Requirements

### 核心流程

* 在 `_select_setup_workflow` 中添加 "Custom provider" 选项
* 在 `_specialize_setup_target` 中添加 custom 分支，调用 `_configure_custom_profile_via_setup`
* 自定义 profile 创建后走标准认证流程（`_ensure_profile_auth`）
* 自定义 profile 创建后自动激活（`manager.use_profile`）
* 非交互模式下 `oh setup custom` 可直接进入 custom 流程
* 保持与现有 `oh provider add` 的行为一致性

### 稳健性增强

* **重复名称处理**：当用户输入的 profile 名称已存在时，提示用户确认覆盖（y/n），而非静默覆盖
* **Base URL 基本校验**：检查 URL 是否以 `http://` 或 `https://` 开头，不合法时提示重新输入

## Acceptance Criteria

* [ ] `oh setup` 交互选择器中出现 "Custom provider" 选项（带样式提示）
* [ ] 选择 Custom 后，引导选择 API 族（Anthropic / OpenAI compatible）
* [ ] 引导输入 profile 名称、显示标签、Base URL、默认模型
* [ ] profile 名称已存在时提示确认覆盖
* [ ] Base URL 不以 http(s):// 开头时提示重新输入
* [ ] 引导输入 API Key 并保存
* [ ] 创建后自动激活该 profile
* [ ] `oh setup custom` 直接进入 custom 流程（跳过选择器）
* [ ] 单元测试覆盖新增分支

## Definition of Done

* Tests added/updated（单元测试覆盖新增分支）
* Lint / typecheck / CI green

## Out of Scope

* 修改 `oh provider add` 命令
* 新增 ProviderProfile 字段
* 支持 OAuth 等非 API Key 认证方式的自定义提供商
* 自定义提供商的模型发现 / 模型列表拉取
* 自定义 profile 在 `oh provider list` 中的 visual 区分标识

## Technical Approach

### 改动点

1. **`_select_setup_workflow`**（cli.py:1376）：在 statuses 迭代后追加一个 "custom" 选项（不在 statuses dict 中，需手动添加 Choice）
2. **`_specialize_setup_target`**（cli.py:1521）：添加 `if target == "custom"` 分支，调用 `_configure_custom_profile_via_setup`
3. **`_configure_custom_profile_via_setup`**（cli.py:1450）：
   - 添加 profile 名称重复检查：查询 `manager.list_profiles()`，若已存在则提示确认覆盖
   - 添加 Base URL 格式校验：检查 `http://` 或 `https://` 前缀
4. **`setup_cmd`**（cli.py:1711）：当 `profile == "custom"` 时，跳过 `_select_setup_workflow`，直接进入 custom 流程

### 关键决策

* custom 选项在 `_select_setup_workflow` 中作为额外 Choice 附加，不修改 statuses dict（保持 statuses 只包含真实 profile）
* 名称覆盖确认后复用 `manager.upsert_profile`（它本身就是 upsert 语义）

## Technical Notes

* 关键文件：src/openharness/cli.py（_select_setup_workflow:1376, _specialize_setup_target:1521, _configure_custom_profile_via_setup:1450, setup_cmd:1711）
* 关键文件：src/openharness/config/settings.py（ProviderProfile:109-132, default_provider_profiles:181-259）
* 关键文件：src/openharness/auth/manager.py（get_profile_statuses:291, use_profile:326）
