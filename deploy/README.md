# Docker 部署说明

当前服务器旧版仍在 `18081` 端口运行。`积分商城3` 默认使用新端口并行部署：

- 后台：`18082`
- 客户端：`18083`

## 首次部署

```bash
cd /root/points_mall
git clone https://github.com/simonmarcion-ship-it/points-mall_v3.git points-mall_v3
cd points-mall_v3
cp deploy/env.example deploy/.env
```

编辑 `deploy/.env`，至少修改：

```bash
MALL_SESSION_SECRET=换成一串随机字符串
MALL_SUPER_ADMIN_USERNAME=你的超级管理员账号
MALL_SUPER_ADMIN_PASSWORD=你的超级管理员密码
```

`MALL_SUPER_ADMIN_USERNAME` / `MALL_SUPER_ADMIN_PASSWORD` 会在后台启动时写入或更新一个“超级管理员”账号。超级管理员可以把客服人员提升为管理员；管理员只能维护发券人员、核销人员等下级权限。

旧的 `MALL_ADMIN_USERNAME` / `MALL_ADMIN_PASSWORD` 仅作为兼容兜底，未显式配置时不会生效。

如需启用 Cargeer 异步补全，再配置：

```bash
CARGEER_ENABLED=1
CARGEER_ACCOUNT=你的账号
CARGEER_PASSWORD=你的密码
CARGEER_CAPTCHA_TOKEN=打码平台 token
```

启动：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
```

查看状态：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
docker logs --tail=100 points-mall-v3-admin
docker logs --tail=100 points-mall-v3-client
```

访问：

```text
http://服务器IP:18082
http://服务器IP:18083
```

## 使用旧版数据试跑

新版本默认使用仓库目录下的 `data/mall.db`。如果要基于旧版库试跑，先复制旧库，避免直接改动旧版线上数据库：

```bash
mkdir -p data
cp /root/points_mall/points-mall/web/data/mall.db data/mall.db
```

确认没问题后再启动 v3。

## 更新部署

```bash
cd /root/points_mall/points-mall_v3
git pull
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
```

如果本次上线包含超级管理员改动，先确认服务器 `deploy/.env` 已配置：

```bash
MALL_SUPER_ADMIN_USERNAME=你的超级管理员账号
MALL_SUPER_ADMIN_PASSWORD=你的超级管理员密码
```

启动后用超级管理员登录，在“客服人员维护”里把需要的人提升为管理员。历史内置的 `wangting` 管理员会被迁移为已删除状态，不会再作为默认管理员使用。

## 停止 v3

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down
```

这不会停止旧版 `18081` 容器。
