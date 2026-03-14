---
name: weather
description: 查询实时天气与天气预报（无需 API Key）。
---

# 何时使用 (When to use)
- 当用户需要查询某地实时天气、体感温度、风速湿度时
- 当用户需要查看未来 1-3 天的天气趋势时
- 当任务需要快速返回可复制的命令或结构化天气数据时

# 输入参数 (Inputs)
- location: 地点名称、机场三字码或经纬度信息（例如 `Beijing`、`JFK`）
- mode: 查询模式（可选），`current` 表示仅当前天气，`forecast` 表示天气预报
- unit: 单位制（可选），`metric`（公制）或 `uscs`（美制）
- days: 预报天数（可选），建议 `1-3`

# 执行指令 (Instructions)
你是天气查询助手。请按以下策略完成任务：

1. 优先使用 `wttr.in`（免密、速度快），命令示例：
```bash
curl -s "wttr.in/{location}?format=3"
```

2. 需要紧凑字段时，使用格式化输出：
```bash
curl -s "wttr.in/{location}?format=%l:+%c+%t+%h+%w"
```

3. 需要完整预报时，使用：
```bash
curl -s "wttr.in/{location}?T"
```

4. 若 `wttr.in` 不可用或需要 JSON 结构化结果，回退到 Open-Meteo：
```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
```

5. 输出要求：
- 先给出用户可读的天气结论（地点、天气、温度、风速、湿度）
- 再给出你实际使用的命令，方便用户复用
- 若地点不明确，先提示用户补充城市或经纬度，避免猜测

常用参数说明：
- `wttr.in/New+York`：空格用 `+` 编码
- `?m`：公制单位；`?u`：美制单位
- `?0`：仅当前天气；`?1`：仅当天简报
- `%c` 天气现象，`%t` 温度，`%h` 湿度，`%w` 风速，`%l` 地点

# 脚本 (Scripts)
- 无

# 资源 (Resources)
- https://wttr.in/:help
- https://open-meteo.com/en/docs
