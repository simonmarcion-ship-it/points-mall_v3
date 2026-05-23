# 积分商城3

这是天选好车主的总项目骨架，分成两个应用：

- `admin`：运营后台，给内部员工使用
- `client`：服务号个人中心，给客户使用
- `shared`：公共数据访问、微信身份、通用工具
- `deploy`：Docker / 部署配置
- `docs`：接口和流程说明

## 目标

- 运营后台继续维护客户、券、核销、导入等能力
- 服务号个人中心只展示客户自己的券和资料
- 客户通过微信授权进入，必要时绑定手机号
- 两边共用同一套数据结构，但权限边界分开

## 推荐结构

```text
积分商城3/
  admin/
  client/
  shared/
  deploy/
  docs/
```

## 下一步

1. 把 `积分商城2` 里现有运营后台逻辑迁到 `admin`
2. 新建 `client` 的微信授权和个人中心页面
3. 在 `shared` 里放统一的数据库与微信绑定逻辑
4. 再补 `docker-compose.yml`

## 当前状态

- `admin`：已留出运营后台目录
- `client`：已留出客户侧目录
- `shared`：已留出共用逻辑目录
- `docs`：已写接口规划和绑定思路

## Cargeer 客户车辆信息

客户端手机号绑定时，会先查本地客户库；如果手机号不存在，可选调用 Cargeer 按手机号反查姓名、门店、车架号、车牌号和车型，并用这些信息创建本地客户。

默认不启用 Cargeer，避免本地开发或 Cargeer 异常时阻断客户注册。启用时配置环境变量：

```powershell
$env:CARGEER_ENABLED="1"
$env:CARGEER_ACCOUNT="你的 Cargeer 登录账号"
$env:CARGEER_PASSWORD="你的 Cargeer 登录密码"
$env:CARGEER_CAPTCHA_TOKEN="打码平台 token"
```

Cargeer 查询失败时，客户仍会以手机号完成注册；系统会在 `vehicle_query_success` / `vehicle_errmsg` 记录查询状态。
