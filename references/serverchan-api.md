# Server酱 Turbo API 参考

> 官网：https://sct.ftqq.com/  
> 本项目用它把晚霞预报推到微信 / 企业微信 / 钉钉 / 飞书等通道。

## 认证

登录 [sct.ftqq.com](https://sct.ftqq.com/) → **SendKey** 页面复制密钥。  
密钥形如：`SCTxxxxxxxxxxxxxxxxxxxxxxxx`

环境变量名（本项目）：

```bash
SERVERCHAN_SENDKEY=SCTxxxxxxxx
```

⚠️ **不要把 SendKey 写进代码或提交到 Git。** 在 Vercel 控制台 → Project → Settings → Environment Variables 中配置。

## 发送接口

```
POST https://sctapi.ftqq.com/<SENDKEY>.send
Content-Type: application/x-www-form-urlencoded
```

也可用 GET（仅适合短消息测试）：

```
https://sctapi.ftqq.com/<SENDKEY>.send?title=标题&desp=正文
```

### 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `title` | ✅ | 消息标题 |
| `desp` | 否 | 正文，支持 Markdown |
| `short` | 否 | 短摘要（部分通道展示） |

### 成功响应示例

```json
{
  "code": 0,
  "message": "",
  "data": {
    "pushid": "...",
    "readkey": "...",
    "error": "SUCCESS",
    "errno": 0
  }
}
```

`code != 0` 表示失败，查看 `message` 字段。

## 本项目用法

### CLI

```bash
export SERVERCHAN_SENDKEY=SCTxxxxxxxx
python scripts/predict-sunset.py --location 杭州 --serverchan
```

### Vercel

| 端点 | 作用 |
|------|------|
| `GET /api/predict` | 仅预测，返回 JSON |
| `GET /api/predict?push=1` | 预测并推送（若配置了 `CRON_SECRET` 需 Bearer） |
| `GET /api/cron` | 定时任务入口：预测 + 推送 |

每日 **16:00（Asia/Shanghai）** = **08:00 UTC**，由 `vercel.json` 的 cron 触发 `/api/cron`。

## 与旧版 sc.ftqq.com 的区别

- 新版域名：`sctapi.ftqq.com` + SendKey 以 `SCT` 开头  
- 旧版 `sc.ftqq.com` / `SCKEY` 已不推荐；本项目仅对接 Turbo 版
