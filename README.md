# 思考强度（thinking-effort）

> 给 AstrBot 用的小插件。**一条指令给模型换思考档位**，不用改配置文件、不用重启后忘记自己改过什么。

版本：v2.0.3.1

---

## 它为什么存在

AstrBot 里改思考强度（`reasoning_effort`），原本要做这些事：

1. 打开 `core/data/cmd_config.json`
2. 找到 `provider` 数组里每一个 provider
3. 往它的 `custom_extra_body` 里加一个字段
4. 小心别把缩进写坏、别把中文写进去
5. 重启实例

provider 一多，这件事就很烦；而且每次想临时换个档（比如问个简单问题、想快一点），都要走一遍。

这个插件把它压成一条聊天指令：

```
/思考 低
```

---

## 四档是什么

**跟 DeepSeek 官方对齐**：`off` / `low` / `high` / `max`。

| 档位 | 写进配置的东西 | 效果 |
| --- | --- | --- |
| `off` | `thinking: {"type": "disabled"}`，同时拿掉 `reasoning_effort` | 完全不思考，最快 |
| `low` | `reasoning_effort: "low"` | 轻度思考 |
| `high` | `reasoning_effort: "high"` | 默认档，日常和写代码够用 |
| `max` | `reasoning_effort: "max"` | 投入最大算力，硬核推理 |

### 为什么不是 minimal / low / medium / high

因为那一套看起来有四档，实际上只有三种效果。

DeepSeek 官方文档里有一张映射表：

| 请求传入 | 实际映射 |
| --- | --- |
| `minimal` | `low` |
| `low` | `low` |
| `medium` | `high` |
| `high` | `high` |
| `xhigh` | `high` |
| `max` | `max` |
| `ultra` | `max` |

也就是说：`minimal` 和 `low` 一样，`medium` 和 `high` 一样。而且那套命名里**没有真正的最高档**（很多人以为 `high` 就是最高，其实 `max` 才是）。

所以 v2.0 直接改成 `off / low / high / max`，跟原生对齐，不绕那一圈。

> 旧配置里如果还写着 `minimal` 或 `medium`，插件会把它显示成对应的新档位（`low` / `high`），不会认不出来。

---

## `off` 特别说明

`off` 不是"把 `reasoning_effort` 设成 `none`"，而是：

```json
"custom_extra_body": {
  "thinking": { "type": "disabled" }
}
```

同时把 `reasoning_effort` 从 `custom_extra_body` 里**删掉**。

两条路一起堵，是因为不同接口对"关闭思考"的处理方式不一样，留着旧的 `reasoning_effort` 有可能会把 `disabled` 盖掉。

**代价**：回得快，但想得浅。简单问答、改个错字、跑个命令，`off` 很合适；写代码、做分析，别关。

---

## 安装

1. 把整个文件夹放到：

   ```
   <你的 AstrBot 实例目录>/core/data/plugins/astrbot_plugin_thinking_effort/
   ```

2. 面板里重载插件。
3. 聊天里发 `/思考` 看当前档位。

不需要额外依赖。

---

## 命令

```
/思考            看当前是什么档，以及每个 provider 分别是什么
/思考 关         不思考，最快
/思考 低         low
/思考 高         high
/思考 最高       max
/思考档          列出可用档位
```

英文也认：`/思考 off`、`/思考 low`、`/思考 high`、`/思考 max`。

---

## 配置项

| 配置项 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `reasoning_effort` | 下拉 | `不修改` | 面板上选一档。选「不修改」则插件不碰配置文件 |
| `apply_on_startup` | bool | `false` | 插件加载时自动套用上面的档位 |
| `only_deepseek` | bool | `true` | 只改 `deepseek/` 开头的 provider |
| `backup` | bool | `true` | 改之前先备份 `cmd_config.json` |
| `max_backups` | int | `3` | 最多留几份备份，超了删最旧的 |
| `verbose` | bool | `true` | 往日志里写操作记录 |

**两种用法，别同时开：**

- 想用聊天指令换档 → 面板里保持「不修改」，`apply_on_startup` 关掉
- 想开机就是某一档 → 面板里选好档位，`apply_on_startup` 打开

两个都开的话，每次插件加载都会把面板那档写回去，你在聊天里改的会被盖掉。

---

## 为什么改完必须重启

AstrBot 的配置是**启动时读进内存**的。

这个插件改的是磁盘上的 `cmd_config.json`。改完之后，内存里还是旧值，所以要重启实例才生效。

插件**故意不自动重启**——重启会断线，包括你正在聊天的那一刻。什么时候重启，留给你自己定。

判断有没有生效，看这个：

```
进程启动时间  vs  cmd_config.json 的修改时间
```

文件比进程新，那就是改了但还没重启。

---

## 踩过的坑

### 跨实例移植后 `/思考` 变成「不认识 [MSG_ID:...]」

同一个插件放到另一个实例，`/思考` 突然回：

```
不认识 [MSG_ID:1234567890]。
```

原因是那个实例（装了别的插件，或者平台适配器不同）会在消息文本里塞方括号标记。`message_str` 实际长这样：

```
[MSG_ID:1234567890] /思考
```

插件把 `[MSG_ID:1234567890]` 当成参数去档位表里找，自然找不到。

v2.0.1 的修法：解析参数之前，先把 `[...]` 这类标记整段抹掉。

```python
raw = re.sub(r"\[[^\[\]]{0,64}\]", " ", raw).strip()
```

限长 64 字符，免得把正常句子里带方括号的内容误伤。

顺带也解决了 `[CQ:at,qq=...]` 这类 CQ 码的干扰。

### 备份文件别放在 `plugins/` 目录里

一开始把备份目录建在 `core/data/plugins/_backup_thinking_effort_xxx/`，结果那个目录里也有 `metadata.yaml`，AstrBot 把它当成了**第二个插件**加载。

备份要放在 `plugins/` 外面（比如 `core/data/_plugin_backups/`）。

---

## 版本记录

| 版本 | 变更 |
| --- | --- |
| 1.0.0 | `/思考` 查看、换档；只改 DeepSeek；带备份 |
| 1.1.0 | 加面板配置项、`apply_on_startup`、备份数量上限 |
| 2.0.0 | 档位改成与 DeepSeek 原生对齐的 `off / low / high / max`；`off` 走 `thinking.type = disabled` |
| 2.0.1 | 修跨实例移植后「`/思考` 读成 `不认识 [MSG_ID:...]`」 |

---

## 许可

MIT
