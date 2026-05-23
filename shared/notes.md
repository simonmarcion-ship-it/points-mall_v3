# 绑定逻辑

推荐把微信身份单独存表，不直接塞进 `customers`：

- `openid`
- `unionid`
- `customer_wid`
- `phone`
- `bound_at`

规则：

1. 先查 session
2. 再查 unionid
3. 没绑定再走手机号验证
4. 命中 `customers.phone` 就绑定现有客户
5. 没命中就新建客户再绑定

