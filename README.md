# ETH 转入压力监控台

一个完全在浏览器本地运行的单页工具，用于手动登记 ETH 转入量、当日高点和已兑现点数，并根据可调整的 `k` 值测算剩余压力。

## 功能

- ETH 转入登记和累计未兑现统计
- 当日高点更新及三档目标价重算
- 兑现点数反推消耗 ETH，并计算压力释放进度
- 兑现记录可保存“下跌起点 → 下跌终点”，手动登记和 DeepSeek 识别结果均可编辑，便于排查重复登记
- 跨自然日自动顺延
- 带时间记录的两小时集中度和风险窗口分析
- 满 5 天后启用近期日均异常预警
- 实际 k 值样本记录及偏差提醒
- IndexedDB 本地持久化
- `ETH_monitor_log.jsonl` 导出与导入恢复
- HTTPS 服务器状态同步与乐观锁冲突检测；同步前先比较本地和云端，差异时以页面内静默提示选择“采用云端”或“本地覆盖云端”
- DeepSeek 服务端代理解析
- DeepSeek Key 服务端验证与一次配置、多端共用
- AI 识别结果编辑、复核和确认执行
- 复用服务器既有监控服务的 `events.jsonl` 产出
- 自动采集事件 ID 幂等去重，同时保留手动补录
- 响应式手机和桌面界面

## 本地运行

直接打开 `index.html`，或使用任意静态文件服务器。

## 数据说明

数据默认只保存在当前浏览器。更换浏览器或设备前，请先导出 JSONL 日志备份。

## 服务器模式

API 代码位于 `server/api_server.py`，提供：

- `GET /health`
- `GET /api/state`
- `PUT /api/state`
- `POST /api/parse`
- `POST /api/inflow`
- `GET/POST /api/collector`

状态写入采用递增 revision。客户端携带旧 revision 写入时，服务器返回 `409`，避免不同设备静默覆盖数据。API Key、同步码和密码不写入 JSONL。

`eth-monitor-event-consumer.service` 只尾读既有 `/opt/eth-key-event-monitor/events.jsonl`，自身不请求上游接口。首次启动以当前文件末尾建立基线，后续新增的真实 ETH 交易所转入会调用 `/api/inflow` 自动累计；`ACC-` 聚合提醒记录会排除，同一事件 ID 再次出现时按重复事件忽略。手动补录入口保持可用。
