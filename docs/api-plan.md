# 接口规划

## admin

- `GET /api/summary`
- `GET /api/customers`
- `GET /api/customers/{wid}`
- `POST /api/coupons/issue`
- `POST /api/coupons/redeem`

## client

- `GET /api/client/wechat/start`
- `GET /api/client/wechat/callback`
- `POST /api/client/bind-phone`
- `GET /api/client/me`
- `GET /api/client/coupons`

## shared

- `wechat_bindings`
- `customer_sessions`
- `sms_codes`

