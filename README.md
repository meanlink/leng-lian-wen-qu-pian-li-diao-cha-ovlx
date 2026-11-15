# 冷链温区偏离调查

分布比较与偏离定位的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery。

## 审计账与封账核验
接入、调查创建、批准、分发启停等业务动作与留痕同事务落库（同成同败，失败回滚不留伪记录），并逐条接入 SHA-256 哈希链：每条留痕携带全账唯一序号与上一条的哈希，追加时锁定单行账本头，并发下序号唯一连续。建链前的旧留痕标记为「未认证历史」，不参与链式核验，也不冒充可信起点。

- 负责人在「审计账本」页封账：把当前链头（高度 + 哈希）写入凭据并下载，凭据须离线另行保存，是核验的唯一锚点。封账后照常记账，旧凭据对旧高度持续有效。
- 同一高度重复封账复用既有记录，不新增封账；导出文件先写临时文件、fsync 后原子改名，写中断后重新封账即可恢复，残缺文件一律 409 不开放下载。
- 核验：`GET /ledger/verifier` 下载仅依赖标准库的 `verify_ledger.py`，离线执行 `python3 verify_ledger.py 账本导出.json 封账凭据.json`，或在页面内上传两份文件。能发现改写、删行、换序与整段截尾，并指出位置；凭据本身带 HMAC，被改写即失效。
- 留痕哈希采用确定性 JSON（键排序、整数值浮点归一），浏览器等中间环节改变数字文本形式不会造成误报。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18201；后端文档 http://localhost:19201/docs；数据库宿主端口 17701。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、封账核验、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；MySQL 8.0；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/scripts/verify_ledger.py（离线核验，仅标准库）；backend/migrations/initial.py（含既有 audits 表链式字段升级）。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=cold-excursion；FRONTEND_PORT=18201；BACKEND_PORT=19201；DB_PORT=17701；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1002/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
