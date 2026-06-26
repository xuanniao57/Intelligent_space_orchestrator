# ABC Square Data API 文档

公网访问地址：

```text
http://58.33.91.82:28002
```

所有业务接口都是只读接口。健康检查 `/health` 不需要鉴权，其他 `/api/v1/*` 接口都需要 HMAC 鉴权。

## 1. 通用限制

- 最多只能查询最近 7 天内的数据。
- 单次查询时间跨度不能超过 7 天。
- 聚合粒度固定为小时。
- 时间格式使用 ISO 8601，例如 `2026-06-11T10:00:00+08:00`。
- 如果时间不带时区，服务端按 `Asia/Shanghai` 处理。
- 时间段接口中，`start_time` 为闭区间，`end_time` 为开区间，即 `[start_time, end_time)`。

## 2. 鉴权方式

请求头：

| Header | 必填 | 说明 |
| --- | --- | --- |
| `X-API-Key` | 是 | 调用方标识 |
| `X-Timestamp` | 是 | Unix 秒级时间戳 |
| `X-Nonce` | 是 | 每次请求唯一随机字符串 |
| `X-Signature` | 是 | HMAC-SHA256 签名，hex 小写字符串 |

签名原文由 6 行组成：

```text
HTTP_METHOD
PATH
CANONICAL_QUERY_STRING
X_TIMESTAMP
X_NONCE
SHA256_HEX_BODY
```

说明：

- `HTTP_METHOD` 使用大写，例如 `GET`。
- `PATH` 是路径，例如 `/api/v1/sensors/hourly`。
- `CANONICAL_QUERY_STRING` 是按参数名和值排序后的查询字符串。
- GET 请求 body 为空，`SHA256_HEX_BODY` 固定为：

```text
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Python 签名示例：

```python
import hashlib
import hmac
import time
import uuid
from urllib.parse import urlencode

api_key = "replace-with-client-key"
api_secret = "replace-with-strong-random-secret"
method = "GET"
path = "/api/v1/sensors/hourly"
params = {
    "start_time": "2026-06-11T10:00:00+08:00",
    "end_time": "2026-06-11T12:00:00+08:00",
    "category": "environment",
}

canonical_query = urlencode(sorted(params.items()))
timestamp = str(int(time.time()))
nonce = uuid.uuid4().hex
body_hash = hashlib.sha256(b"").hexdigest()
payload = "\n".join([method, path, canonical_query, timestamp, nonce, body_hash])
signature = hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

headers = {
    "X-API-Key": api_key,
    "X-Timestamp": timestamp,
    "X-Nonce": nonce,
    "X-Signature": signature,
}
```

完整请求 URL：

```text
http://58.33.91.82:28002/api/v1/sensors/hourly?start_time=2026-06-11T10%3A00%3A00%2B08%3A00&end_time=2026-06-11T12%3A00%3A00%2B08%3A00&category=environment
```

## 3. 接口

### 3.1 传感器小时聚合

```http
GET /api/v1/sensors/hourly
```

数据源：`post_data.sensors_data`

时间字段选择：

- 只使用 `upload_time`。
- `upload_time` 是 Unix 毫秒时间戳。
- 服务端会把请求中的北京时间转成 UTC 毫秒时间戳，然后直接过滤 `upload_time`。
- 小时聚合展示时使用 `to_timestamp(upload_time / 1000.0) AT TIME ZONE 'Asia/Shanghai'` 的等价逻辑。

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `start_time` | 是 | 开始时间，包含 |
| `end_time` | 是 | 结束时间，不包含 |
| `category` | 否 | 当前仅支持 `environment`，默认 `environment` |

返回字段：

- `device_info`: 设备数量、在线设备数量。
- `temperature`: 小时平均温度。
- `humidity`: 小时平均湿度。
- `pm25`: 小时平均 PM2.5。
- `pm10`: 小时平均 PM10。
- `noise`: 小时平均噪声。
- `wind_power`: 小时平均风力/风速字段。
- `pressure`: 小时平均气压。

响应示例：

```json
{
  "status": "success",
  "query": {
    "start_time": "2026-06-11T10:00:00+08:00",
    "end_time": "2026-06-11T12:00:00+08:00",
    "timezone": "Asia/Shanghai",
    "aggregation": "hour",
    "category": "environment"
  },
  "data": [
    {
      "hour_start": "2026-06-11T10:00:00+08:00",
      "record_count": 12,
      "device_info": {
        "device_count": 4,
        "online_device_count": 3
      },
      "temperature": 28.3,
      "humidity": 67.5,
      "pm25": 21.2,
      "pm10": 45.1,
      "noise": 55.4,
      "wind_power": 2.1,
      "pressure": 1012.4
    }
  ]
}
```

### 3.2 情绪人口小时聚合

```http
GET /api/v1/emotions/hourly
```

数据源：`post_data.cam_emotions`

时间字段：

- `date_time` 是 `timestamptz`。
- 服务端会把请求中的北京时间转成 UTC 后过滤 `date_time`。
- 返回的 `hour_start` 按 `Asia/Shanghai` 展示。
- 接口使用 `[start_time, end_time)`，结束时间不包含。

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `start_time` | 是 | 开始时间，包含 |
| `end_time` | 是 | 结束时间，不包含 |
| `category` | 否 | 当前仅支持 `all`，默认 `all` |

响应示例：

```json
{
  "status": "success",
  "query": {
    "start_time": "2026-06-11T10:00:00+08:00",
    "end_time": "2026-06-11T12:00:00+08:00",
    "timezone": "Asia/Shanghai",
    "aggregation": "hour",
    "category": "all"
  },
  "data": [
    {
      "hour_start": "2026-06-11T10:00:00+08:00",
      "emotion_counts": {
        "unknown": 0,
        "surprised": 1,
        "panic": 0,
        "disgusted": 0,
        "happy": 23,
        "sad": 2,
        "angry": 0,
        "poker-faced": 6
      },
      "total_emotion_count": 32
    }
  ]
}
```

### 3.3 总人口数量小时聚合

```http
GET /api/v1/population/hourly
```

数据源：`post_data.cam_human_number_all`

业务定义：总人口数量使用 `human_in_area`。

时间字段：

- `date_time` 是 `timestamptz`。
- 服务端会把请求中的北京时间转成 UTC 后过滤 `date_time`。
- 返回的 `hour_start` 按 `Asia/Shanghai` 展示。
- 接口使用 `[start_time, end_time)`，结束时间不包含。

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `start_time` | 是 | 开始时间，包含 |
| `end_time` | 是 | 结束时间，不包含 |
| `category` | 否 | 当前仅支持 `all`，默认 `all` |

响应示例：

```json
{
  "status": "success",
  "query": {
    "start_time": "2026-06-11T10:00:00+08:00",
    "end_time": "2026-06-11T12:00:00+08:00",
    "timezone": "Asia/Shanghai",
    "aggregation": "hour",
    "category": "all"
  },
  "data": [
    {
      "hour_start": "2026-06-11T10:00:00+08:00",
      "avg_human_in_area": 128.5,
      "max_human_in_area": 151
    }
  ]
}
```

## 4. 错误码

| HTTP 状态码 | 说明 |
| --- | --- |
| `401` | 鉴权失败、签名错误、时间戳过期或 nonce 重放 |
| `403` | 客户端 IP 不在允许列表中 |
| `422` | 参数格式错误、时间范围超过限制或查询超出最近 7 天 |
| `429` | 请求频率超过限制 |
| `500` | 服务内部错误 |
| `503` | 服务端未配置 API Key/Secret 或数据库配置不完整 |

健康检查：

```bash
curl http://58.33.91.82:28002/health
```
