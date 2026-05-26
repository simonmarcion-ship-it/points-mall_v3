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

## 当前试用功能

新版积分商城后台已支持以下试用能力：

1. 客户管理支持多种查询条件，包括手机号、WID、昵称、车牌号、车架号、车主姓名。
2. 新增客户时，输入手机号后可以自动从 Cargeer 查询车辆信息，并将姓名、车系、车架号、车牌号、购车门店等信息预填到表单。
3. 优惠券新增“发券门店”字段。发券门店基于发券人所属门店自动生成，例如航星客服人员发券，则该券发券门店为航星。
4. 优惠券新增“使用门店”字段。发券时可以设置该券可在哪些门店使用，支持全部门店、当前登录人员所属门店、客户归属门店、指定一个或多个门店。
5. 优惠券新增“核销门店”字段。优惠券最终由哪个门店的客服人员核销，核销门店就记录为该客服人员所属门店。
6. 新增“优惠券作废”功能。在客户详情的优惠券列表中，右键特定优惠券可发起作废，确认后该券对客户端不可见，但后台仍可查看记录。

## 门店与客服规则

- 每个客户有“客户归属门店”，用于记录客户本身所属门店。
- 每个后台客服账号也有“所属门店”，用于决定发券门店、核销门店等操作归属。
- 后续正式使用时，会有多个客服账号，每个账号绑定一个特定门店。
- 发券门店不一定等于客户归属门店，也不一定等于使用门店；三者分别表示券的发放归属、客户归属、可使用范围。
- 门店列表由系统维护为 `stores` 门店总表，发券时的可用门店选择来自该门店总表。

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

## 服务号客户端上线逻辑

客户端最终会挂到“天选好车主”服务号菜单里的“个人中心”。客户侧入口不是后台系统，而是：

```text
http://pointmall.hajimitech.com/client/
```

上线前不要直接替换服务号菜单。正确顺序是：

1. 本地用 `http://127.0.0.1:8010/?dev=1` 测页面和手机号绑定。
2. 服务器用 `http://pointmall.hajimitech.com/client/?dev=1` 测线上页面和手机号绑定。
3. 配好公众号网页授权域名后，用 `http://pointmall.hajimitech.com/client/` 测微信 `openid` 自动登录。
4. 全部测试通过后，再用自定义菜单 API 把原微盟链接替换为自己的客户端地址。

`?dev=1` 是开发测试模式，只用于绕过微信网页授权。测试真正的微信免登录时，不能带 `?dev=1`。

## 微信 openid 免登录流程

公众号 H5 页面不能直接从前端拿 `openid`。必须通过微信网页授权：

1. 用户在微信里打开客户端页面。
2. 客户端发现没有本地登录态，自动跳转到 `/api/client/wechat/start`。
3. 后端拼出微信网页授权 URL，并把用户原来访问的路径放进 `state`。
4. 微信授权后回调 `WECHAT_OAUTH_REDIRECT_URI`，也就是 `/api/client/wechat/callback`。
5. 后端用回调里的 `code` 请求微信接口，换取 `openid`，可能还会拿到 `unionid`、昵称和头像。
6. 后端查询 `wechat_bindings`：
   - 如果这个 `openid` 已经绑定过客户，直接写客户端登录 cookie，用户免手机号验证进入个人中心。
   - 如果没绑定过，后端临时保存微信身份，回到客户端手机号验证页。
7. 用户首次手机号验证成功后，系统写入 `wechat_bindings`，建立 `openid -> customer_wid / phone` 的绑定。
8. 下次同一个微信用户进入页面，就可以通过 `openid` 自动登录。

因此，“退出登录后重新打开仍免手机验证”的前提是：不是 `?dev=1`，并且该微信用户已经在 `wechat_bindings` 中绑定过手机号。

`unionid` 为空是正常情况。当前服务号内免登录主要依赖 `openid`。

## 服务器域名与 Nginx 反向代理

当前测试域名：

```text
pointmall.hajimitech.com
```

DNS 中添加 A 记录：

```text
pointmall -> 服务器公网 IP
```

Nginx 将 `/client/` 转发到 Docker 中的客户端端口 `18083`。示例配置：

```nginx
server {
    listen 80;
    server_name pointmall.hajimitech.com;

    location = / {
        return 302 /client/;
    }

    location = /client {
        return 301 /client/;
    }

    location /client/ {
        proxy_pass http://127.0.0.1:18083/;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /assets/ {
        proxy_pass http://127.0.0.1:18083/assets/;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/client/ {
        proxy_pass http://127.0.0.1:18083/api/client/;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

修改后执行：

```bash
nginx -t
systemctl reload nginx
```

如果看到 `Welcome to nginx!`，通常说明访问落到了域名根路径 `/` 或 Nginx 默认站点，而不是客户端 `/client/`。当前配置用 `location = / { return 302 /client/; }` 兜底。

## 公众号网页授权域名

公众号后台路径：

```text
设置与开发 -> 开发接口管理 -> 网页服务 -> 网页授权获取用户基本信息
```

网页授权域名填写：

```text
pointmall.hajimitech.com
```

不要填写：

```text
http://pointmall.hajimitech.com
pointmall.hajimitech.com/client
```

微信会要求上传校验文件，例如：

```text
MP_verify_xxxxx.txt
```

该文件必须能通过下面地址访问：

```text
http://pointmall.hajimitech.com/MP_verify_xxxxx.txt
```

服务器可以这样创建校验文件：

```bash
mkdir -p /var/www/pointmall
echo '校验文件内容' > /var/www/pointmall/MP_verify_xxxxx.txt
```

并在 Nginx 里增加对应 `location`：

```nginx
location = /MP_verify_xxxxx.txt {
    root /var/www/pointmall;
}
```

保存网页授权域名后，微信才允许该域名通过网页授权获取当前服务号用户的 `openid`。

## 服务器 deploy/.env

服务器真实配置文件是：

```text
/root/points_mall/points-mall_v3/deploy/.env
```

这个文件不进 Git。误删后可以从 `deploy/env.example` 复制一份，再补真实值：

```bash
cd /root/points_mall/points-mall_v3
cp deploy/env.example deploy/.env
nano deploy/.env
```

客户端微信授权相关变量：

```env
WECHAT_APPID=服务号 AppID
WECHAT_APPSECRET=服务号 AppSecret
WECHAT_OAUTH_REDIRECT_URI=http://pointmall.hajimitech.com/api/client/wechat/callback
```

短信测试阶段可以先关闭：

```env
SMS_ENABLED=0
```

关闭后验证码使用：

```text
000000
```

Cargeer 相关变量只放在服务器 `deploy/.env`，不要写入 `deploy/env.example`：

```env
CARGEER_ENABLED=1
CARGEER_ACCOUNT=
CARGEER_USERNAME=
CARGEER_PASSWORD=
CARGEER_CAPTCHA_TOKEN=
JFBYM_TOKEN=
CARGEER_TIMEOUT=15
```

`deploy/env.example` 是模板文件，会进 Git，不能放真实账号、密码、token。

## 部署与重启

服务器拉取最新代码并重启客户端：

```bash
cd /root/points_mall/points-mall_v3
git pull origin main
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build client
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
```

如果后台也有改动：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build admin client
```

旧版系统仍在 `18081` 端口运行，不要动。

当前 v3 端口：

```text
admin  -> 18082
client -> 18083
```

## 验证 openid 是否绑定

服务器查询最近的微信绑定：

```bash
cd /root/points_mall/points-mall_v3

python3 - <<'PY'
import sqlite3
conn = sqlite3.connect("data/mall.db")
conn.row_factory = sqlite3.Row

rows = conn.execute("""
SELECT
  id,
  substr(openid, 1, 8) || '...' AS openid_mask,
  CASE WHEN unionid IS NULL OR unionid = '' THEN '' ELSE substr(unionid, 1, 8) || '...' END AS unionid_mask,
  customer_wid,
  phone,
  nickname,
  bound_at,
  last_login_at
FROM wechat_bindings
ORDER BY id DESC
LIMIT 10
""").fetchall()

print("rows:", len(rows))
for r in rows:
    print(dict(r))
PY
```

看到对应手机号和 `openid_mask`，说明已经拿到微信 `openid` 并完成绑定。

最终免登录测试：

1. 手机微信打开 `http://pointmall.hajimitech.com/client/`。
2. 首次用手机号和验证码完成绑定。
3. 查询 `wechat_bindings`，确认有记录。
4. 页面点“退出登录”。
5. 关闭页面，再用微信打开同一链接。
6. 如果直接进入个人中心，不再要求手机号验证码，说明 `openid` 免登录链路成功。

## 后续替换服务号菜单

当前线上“个人中心”仍是微盟链接，例如：

```text
http://t.weimob.com/...
```

只有当以下内容全部测试通过后，才修改服务号菜单：

1. `http://pointmall.hajimitech.com/client/?dev=1` 可以打开并用 `000000` 绑定。
2. `http://pointmall.hajimitech.com/client/` 可以触发微信网页授权。
3. 首次绑定后，`wechat_bindings` 中能看到对应 `openid`。
4. 退出登录后重新进入，可以通过 `openid` 自动免验证登录。

菜单替换仍要通过 API 自定义菜单发布，不要在公众号后台直接保存预览菜单，以免覆盖线上 API 菜单。
