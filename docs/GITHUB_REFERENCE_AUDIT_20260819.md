# GitHub 参照项目审计（2026-08-19 快照）

本文件是 Minos Bench 独立公开仓库内可读的参照审计，使用只读 `gh` 元数据、README 和相关源码检查形成。

## 审计结论

| 项目 | 2026-08-19 快照 | 检查位置 | 决策 |
|---|---|---|---|
| [DeepEval](https://github.com/confident-ai/deepeval) | 17,704 stars、1,826 forks、Apache-2.0；当天仍有提交 | README、`deepeval/evaluate/`、数据集、指标、模型集成与本地存储目录 | 保留现有 Python 依赖，不让它替代 Minos Bench 自己的题集治理、运行错误分流和发布裁决。 |
| [Promptfoo](https://github.com/promptfoo/promptfoo) | 24,376 stars、2,210 forks、MIT；当天仍有提交 | README、`src/commands/init.ts`、Dockerfile | 借鉴 `init → eval → view`、示例项目、初始化失败清理和健康检查；不引入 Node 技术栈。 |
| [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) | 2,577 stars、662 forks、MIT；当天仍有提交 | README、`src/inspect_ai/_view/view.py` | 借鉴执行日志与 viewer 分离、默认本机回环地址以及失败不混成内容分的边界。 |
| [Opik](https://github.com/comet-ml/opik) | 21,479 stars、1,708 forks、Apache-2.0；当天仍有提交 | README、根 `opik.ps1`、Docker Compose 服务与健康检查 | 不采用完整平台。其 ClickHouse、MySQL、Redis、MinIO、ZooKeeper、前后端栈超出个人 POC；只借鉴启动前检查和健康状态。 |

## 转化为 Minos Bench 的产品决定

1. 第一次使用路径改成“配置 → 运行 → 查看”，不把完整科学矩阵当作第一屏。
2. 快速体验只要求一个目标模型和一个 Judge，但明确声明三个目标槽位相同，不能生成有效模型比较。
3. 执行结果和日志继续本地追加保存，API/解析错误与回答质量失败分开。
4. 本机工作台默认只绑定 `127.0.0.1`；当前进程级 BYOK 不包装成公网多租户部署。
5. 不通过再叠加框架、数据库或 Docker 服务解决面试 POC 的易用性问题。

## 使用边界

stars、forks 与最近提交只是采用度和维护信号，不代表这些项目必然适合 Minos Bench。本轮没有复制上游源码，也没有对四个项目做完整安全审计。Minos Bench 的最终行为仍由本仓库源码、冻结数据、测试和运行工件裁决。
