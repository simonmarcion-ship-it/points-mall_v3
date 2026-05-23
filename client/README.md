# 服务号客户端

这是“天选好车主”服务号底部菜单“个人中心”要打开的客户侧 H5。

客户只能看到自己的资料、积分和优惠券；运营后台功能不放在这里。

## 目录

```text
client/
  web/
    backend/        FastAPI 客户端接口
    frontend/       手机端 H5 页面
    run_server.py   本地启动入口
```

## 本地启动

```powershell
cd .\积分商城3\client\web
python .\run_server.py
```

浏览器打开：

```text
http://127.0.0.1:8010
```

## 当前状态

当前是开发骨架：

- 已有个人中心移动端页面
- 已有客户资料和优惠券接口
- 已有手机号绑定接口占位
- 已有微信授权入口和回调占位
- 默认读取 `../../admin/web/data/mall.db`

微信正式接入时，需要补齐：

- 公众号 `appid`
- 公众号 `appsecret`
- 网页授权域名
- 短信验证码服务
- `unionid/openid` 绑定逻辑

