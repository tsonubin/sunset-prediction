# Sunsethue API 参考

> 官方文档：https://sunsethue.com/dev-api

## 端点

```
GET https://api.sunsethue.com/event?latitude={lat}&longitude={lng}&date={date}&type={sunset|sunrise}
```

## 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `latitude` | float | ✅ | 纬度（WGS84，-90~90） |
| `longitude` | float | ✅ | 经度（WGS84，-180~180） |
| `date` | string | ✅ | 日期 `YYYY-MM-DD` |
| `type` | string | ✅ | `sunset` 或 `sunrise` |

## 认证

Header: `X-API-Key: {API_KEY}`  
或 Query 参数: `?key={API_KEY}`  

⚠️ 注意：不接受 `Authorization: Bearer` 方式。

## 响应

```json
{
  "time": "2026-02-22T20:23:23.349Z",
  "location": {
    "latitude": 41.4,
    "longitude": 2.2
  },
  "data": {
    "type": "sunset",
    "model_data": true,
    "quality": 0.45,
    "cloud_cover": 0.32,
    "quality_text": "Good",
    "time": "2026-02-22T17:32:00.000Z",
    "direction": 256.7,
    "magics": {
      "blue_hour": ["17:55", "18:07"],
      "golden_hour": ["17:17", "17:49"]
    }
  }
}
```

## 响应字段

| 字段 | 说明 |
|------|------|
| `data.quality` | 质量评分 0-1 |
| `data.quality_text` | 文字描述 ("Poor"/"Good"/"Excellent" 等) |
| `data.cloud_cover` | 云量 0-1 |
| `data.time` | 日落/日出时间 (UTC) |
| `data.direction` | 太阳方位角（度） |
| `data.magics.golden_hour` | 黄金时段 [start, end] |
| `data.magics.blue_hour` | 蓝色时刻 [start, end] |

## 定价

- 免费：个人/爱好项目，每日免费额度
- 付费：商业使用，按量计费
- 详情：https://sunsethue.com/pricing

## 注册

https://sunsethue.com/account/signin → 注册 → API Keys

## 设置

```bash
export SUNSETHUE_API_KEY=your_key_here
```
