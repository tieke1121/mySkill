# mySkill · 可执行研究技能

| Skill | 用途 |
| --- | --- |
| [stock-research](stock-research/SKILL.md) | 股票基本面研究与可复算估值 |
| [micro-saas-scout](micro-saas-scout/SKILL.md) | 发现并核验面向英语市场的微型 SaaS 创业机会 |

两个 skill 可独立安装。以下先介绍股票研究，微型 SaaS 的安装与执行方式见文末。

## 股票研究

一个可复用的 `stock-research` skill。直接提供股票名称或代码，默认输出中文全面研究；也可以只研究财务、护城河、估值、风险、增长、机构逻辑、多空观点或最新财报。

核心文件是 [SKILL.md](stock-research/SKILL.md)。默认覆盖过去五个可得完整财年、最新披露、12–24 个月展望与 5–10 年条件增长情景，重点分析护城河。资料不足会限制对应结论，不补造数据。

## 安装

先克隆或下载本仓库。使用 GitHub CLI 的示例：

```bash
gh repo clone tieke1121/mySkill
cd mySkill
```

安装的是仓库内整个 **`stock-research/` 文件夹**，不是整个仓库，也不是单独的 `SKILL.md`。参考文档、脚本和样例需要保留相对位置。若目标位置已有同名自定义版本，先比较并备份，再替换完整目录。

### Codex

在本机使用的默认个人 skills 路径安装：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R stock-research "${CODEX_HOME:-$HOME/.codex}/skills/"
```

新对话中可输入 `$stock-research 分析 AAPL`，或直接提供股票名。实际自动匹配由客户端决定；未触发时显式指定 skill。

### Antigravity App / IDE / CLI

按 [Antigravity 官方技能文档](https://antigravity.google/docs/skills)（核对日期：2026-11-05），共享全局目录为 `~/.gemini/config/skills/`：

```bash
mkdir -p ~/.gemini/config/skills
cp -R stock-research ~/.gemini/config/skills/
```

项目内使用时，复制到目标项目的 `.agents/skills/stock-research/`。旧版客户端路径可能不同，以所用版本的官方说明为准。

新对话中输入 `/stock-research 分析 AAPL` 或提及 `stock-research`。CLI 可用 `/skills reload` 重新加载；IDE 可在 Customizations 查看已发现的 skills。`agents/openai.yaml` 是 Codex 展示元数据，研究规则和计算脚本不依赖它。

以上是目录安装方式；本仓库没有声明自己是 Antigravity 插件包，不把插件安装器的支持与 skill 文件格式兼容混为一谈。

Windows 可将整个目录复制到用户目录下对应位置，例如 `%USERPROFILE%\.gemini\config\skills\stock-research\`。上面的 shell 命令面向 macOS/Linux。

## 使用示例

- `英伟达`：默认全面研究；证券身份不明确时才澄清。
- `只分析腾讯的护城河，与主要对手比较`：专项研究。
- `分析贵州茅台过去五年财务，重点看现金流`：财务研究。
- `解读 AAPL 最新财报，区分公司指引和市场预期`：财报研究。
- `截至 2025 年底分析某股票，只用当时公开的信息`：历史截面研究。

最新研究需要宿主具备可用的联网检索能力。无网络时可分析已有材料，并说明材料截面。skill 本身不提供付费行情/共识数据库，不执行证券交易。

## 可复算估值

随附计算器只依赖 Python 3.9+ 标准库。先读 [输入约定和支持边界](stock-research/references/model-contract.md)。

```bash
python3 stock-research/scripts/dcf.py --help
python3 stock-research/scripts/dcf.py stock-research/assets/dcf-example.json
```

样例完全虚构。实际研究须从披露和有依据的假设生成输入；计算器不会替你验证来源或预测。支持带日期现金流、FCFF/FCFE、权益桥接、ADR/汇率换算、敏感性和固定其他条件的反向终值现金流计算，不覆盖全部行业估值方法。

## 验证与维护

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖独立闭式解、时间/量级/股份换算、权益桥接、无效输入、命令行文件保护和整个 skill 搬迁后的可执行性。格式检查还可以使用 Codex skill-creator 提供的 `quick_validate.py`。

[行为验收案例](stock-research/references/behavior-evaluation.md)用于实际客户端/模型评估，包含缺失报表、银行、历史截面、共识错位、风险与模型冲突等场景。它们是验收规范，不能因为数值测试通过就宣称研究行为全部通过。

验证范围：本次提供并运行数值与文件包测试；Antigravity 的客户端发现、触发及完整股票研究尚未实测。安装格式兼容、计算正确与研究结论可靠是三种不同的验证。

更新时拉取仓库最新版本，比较本地修改后替换已安装的 `stock-research/`，再按上述方法重新加载。分析输出应保存至任务目录，不写回 skill 安装目录。

## 微型 SaaS 机会侦察

`micro-saas-scout` 实际调用宿主提供的搜索/浏览工具发现和核验产品，再使用 Python 3.9+ 标准库脚本校验数据、识别重复产品、比较历史并生成 Markdown 与 JSON。脚本本身不是独立网络爬虫；完整研究需要具备联网能力的 agent。

将整个文件夹安装到 Codex 的个人 skills 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R micro-saas-scout "${CODEX_HOME:-$HOME/.codex}/skills/"
```

已有同名自定义版本时先比较差异，避免直接覆盖。使用示例：

- `$micro-saas-scout 寻找适合个人开发者做的英语市场微型 SaaS`：默认初筛约 20–30 个候选，最多推荐 5 个。
- `$micro-saas-scout 深挖 <产品名或官网>，重点分析首批客户、MVP 和验证步骤`。
- `$micro-saas-scout 只看电商运营工具，排除依赖广告投放的机会`。
- `$micro-saas-scout 用 2 个产品试跑，并明确证据缺口`：缩小范围并标记 smoke-test。

默认资源为 1 人、每周 15–20 小时、4–6 周首个可收费版本、每月人民币 2,000 元验证预算；每次任务可覆盖。默认报告目录为 `~/micro-saas-research/runs/`，不自动联系客户、付费购买数据或创建定时任务。

准备研究输入时读取 [数据契约与筛选规则](micro-saas-scout/references/evaluation.md)，联网研究参照 [搜索与核验流程](micro-saas-scout/references/discovery.md)。手动执行辅助脚本：

```bash
python3 micro-saas-scout/scripts/manage_results.py validate /absolute/path/input.json
python3 micro-saas-scout/scripts/manage_results.py save /absolute/path/input.json \
  --output /absolute/path/new-run-directory \
  --history /absolute/path/previous-run/results.json
```

无历史时省略 `--history`。目标目录必须不存在，以保护旧快照。测试执行方式仍为 `python3 -m unittest discover -s tests -v`，覆盖证据引用、未知收入、重复身份、历史变化和安装后可执行性。结构测试不能代替研究质量验收；首次联网试跑的范围与结论在交付时单独说明。
