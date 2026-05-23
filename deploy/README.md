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
```

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

## 停止 v3

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down
```

这不会停止旧版 `18081` 容器。
