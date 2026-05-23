# 积分商城后台

这是给公司人员使用的本地后台雏形，已经拆成前端、后端和数据库三层。

## 目录

```text
web/
  backend/        FastAPI 后端、SQLite 数据库访问、Excel 导入
  frontend/       静态前端页面
  data/mall.db    SQLite 数据库，首次启动时自动生成
  run_server.py   启动入口
```

爬虫和原始 Excel 数据放在同级目录：

```text
../crawler/
```

## 启动

```powershell
cd .\积分商城\web
.\start_backend.ps1
```

浏览器打开：

```text
http://127.0.0.1:8001
```

停止后端：

```powershell
cd .\积分商城\web
.\stop_backend.ps1
```

检查后端是否正在运行：

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8001/api/summary' -UseBasicParsing
```

## 数据库

数据库文件固定在：

```text
积分商城/web/data/mall.db
```

首次启动时，如果数据库没有客户数据，后端会从 `crawler` 目录里的 Excel 自动导入：

- `微盟客户详情_解析结果.xlsx`
- `微盟客户优惠券明细_解析结果.xlsx`
- `微盟客户数据_全部13776条.xlsx`

后续发券、核销、操作流水都会写入 SQLite，不再只存在内存或 JSON 里。

### 数据库迁移

正式结构变更走迁移机制，不直接手改生产库表结构。

```powershell
cd .\积分商城3\admin\web
python .\migrate_db.py
```

迁移记录保存在数据库表：

```text
schema_migrations
```

当前迁移文件放在：

```text
backend/migrations/
```

新增表、字段、索引时，应新增一个迁移文件，并登记到 `backend/migrations/runner.py` 的 `MIGRATIONS` 列表。

## 爬虫结果和业务数据库的关系

`crawler` 目录里的 Excel 是旧商城爬取结果，属于“来源数据”。

`web/data/mall.db` 是后台系统真正读写的业务数据库。网页不会直接操作 Excel，也不会在你重新跑爬虫后自动更新数据库。

当前建议至少区分两类数据库：

- 开发/演示库：`web/data/mall.db`，用于本地开发、页面演示、流程测试。
- 生产库：正式给甲方使用时单独建立，不能随意删除或重建。

你每次重新跑一批爬虫，如果想让本地网页看到最新 Excel 数据，需要手动刷新开发数据库：

```powershell
cd .\积分商城\web
python .\refresh_db.py
```

刷新脚本会先备份当前数据库到：

```text
web/data/backups/
```

然后删除并重建 `web/data/mall.db`。

导入时会优先读取 Joblib 结果文件：

- `微盟客户详情_解析结果_Joblib.xlsx`
- `微盟客户优惠券明细_解析结果_Joblib.xlsx`

如果 Joblib 文件不存在或为空，才回退到普通结果文件。

注意：刷新开发库会清掉当前开发库里手工发券、核销等测试数据。正式生产库不能这样刷新，生产库需要走“导入批次 + 对账 + 备份 + 回滚”的流程。

刷新开发库会重新执行迁移，然后从爬虫 Excel 导入客户和券，再根据客户归属门店重建 `stores` 门店主表，并补齐样本后台人员。

## Docker 部署

Docker 部署文件放在：

```text
积分商城/docker/
```

生产容器默认读取：

```text
积分商城/docker/data/mall.db
```

生产模式下不会自动从 Excel 导入数据。部署说明见：

```text
积分商城/docker/README.md
```
