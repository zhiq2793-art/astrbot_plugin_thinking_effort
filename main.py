# -*- coding: utf-8 -*-
"""
思考强度 · Thinking Effort  v2.0
==================================

【v2.0 改了什么】

v1.1 的档位是 minimal / low / medium / high，
照的是 OpenAI 那套习惯叫法。但 DeepSeek 原生只认 low / high / max，
而且它有一张映射表：

    请求传入      实际映射
    minimal   →   low
    low       →   low
    medium    →   high
    high      →   high
    xhigh     →   high
    max       →   max
    ultra     →   max

所以 v1.1 那四档其实只有三种效果，而且缺了真正的最高档。

v2.0 改成跟 DeepSeek 原生对齐的四档：off / low / high / max。

【四档是什么】

    off    完全关闭思考
           写的是 custom_extra_body.thinking = {"type": "disabled"}
           同时把 reasoning_effort 拿掉，两条路都堵死。
           用于简单问答，追求最快。

    low    轻度思考。写 reasoning_effort = "low"

    high   默认档。写 reasoning_effort = "high"

    max    最大算力。写 reasoning_effort = "max"

【为什么必须重启】

AstrBot 的配置是启动时读进内存的。
改文件只是改文件，内存里还是旧的，所以必须重启才生效。

本插件不自动重启 —— 因为重启会断线，
包括正在跟你说话的那一刻。重启的时机留给你自己定。

【安全】

  1. 只允许管理员使用
  2. 每次改之前都备份（文件名带时间戳，最多留 N 份）
  3. 整体 json 读入写回，保留其它所有字段
  4. 只动 custom_extra_body 里的 reasoning_effort 和 thinking，不碰别的

【路径怎么找】

本文件位于：
    <实例>/core/data/plugins/astrbot_plugin_thinking_effort/main.py

往上退三层就是 <实例>/core/data，配置就在那儿：
    <实例>/core/data/cmd_config.json

用相对位置推算，所以实例换路径也不用改代码。
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


# 用户怎么说 → 实际档位
LEVELS = {
    # 关
    "off": "off",
    "none": "off",
    "关": "off",
    "关闭": "off",
    "关掉": "off",
    "不思考": "off",
    "no": "off",
    # 低
    "low": "low",
    "min": "low",
    "minimal": "low",
    "低": "low",
    "最低": "low",
    "快": "low",
    # 高（默认）
    "high": "high",
    "medium": "high",
    "中": "high",
    "高": "high",
    "默认": "high",
    "default": "high",
    # 最高
    "max": "max",
    "最高": "max",
    "最大": "max",
    "ultra": "max",
}

VALID = ("off", "low", "high", "max")

# 用于显示
DISPLAY = {
    "off": "关 off · 不思考，最快",
    "low": "低 low · 轻度思考",
    "high": "高 high · 默认档",
    "max": "最高 max · 想得最细最慢",
    "none": "未设置（跟模型默认走）",
}

USAGE = (
    "用法：\n"
    "  /思考          看当前档位\n"
    "  /思考 关       不思考，最快\n"
    "  /思考 低       low\n"
    "  /思考 高       high（默认）\n"
    "  /思考 最高     max"
)


class ThinkingEffortPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}

        # main.py -> 插件目录 -> plugins -> data
        self.data_dir = Path(__file__).resolve().parent.parent.parent
        self.cfg_path = self.data_dir / "cmd_config.json"

        logger.info(f"[思考强度] 配置文件路径: {self.cfg_path}")

    # ---------------- 面板配置 → 自动应用 ----------------

    async def initialize(self):
        """插件加载时调用：若面板上选了档位，就写进配置文件。

        写入之后仍然要重启实例才生效（配置是启动时读进内存的）。
        所以这里的做法是「提前把文件改好」，下一次重启自然就是新的。
        """
        if not self.config:
            return

        target = str(self.config.get("reasoning_effort", "不修改")).strip()
        if target in ("", "不修改", "none"):
            if self.config.get("verbose", True):
                logger.info("[思考强度] 面板未指定档位，不自动修改配置文件")
            return

        # 兼容旧版残留值
        target = LEVELS.get(target.lower(), target)
        if target not in VALID:
            logger.warning(f"[思考强度] 面板里的档位不认识：{target}，跳过")
            return

        if not self.config.get("apply_on_startup", False):
            if self.config.get("verbose", True):
                logger.info("[思考强度] apply_on_startup 未开启，跳过自动应用")
            return

        if not self.cfg_path.exists():
            logger.error(f"[思考强度] 找不到配置文件：{self.cfg_path}")
            return

        try:
            data = self._load()
        except Exception as e:
            logger.error(f"[思考强度] 读配置失败：{e}")
            return

        only_ds = bool(self.config.get("only_deepseek", True))
        bak_name = None
        if self.config.get("backup", True):
            try:
                bak_name = self._backup()
            except Exception as e:
                logger.error(f"[思考强度] 备份失败，为安全起见不修改：{e}")
                return

        changed = self._apply_level(data, target, only_ds)

        if not changed:
            if self.config.get("verbose", True):
                logger.info(f"[思考强度] 配置里已经是 {target}，无需改动")
            return

        try:
            self._save(data)
        except Exception as e:
            logger.error(f"[思考强度] 写配置失败：{e}（备份：{bak_name}）")
            return

        logger.info(
            f"[思考强度] 面板档位 {target} 已写入 {len(changed)} 个 provider"
            f"（仅 DeepSeek={only_ds}，备份={bak_name}）。重启后生效。"
        )

    # ---------------- 核心：改档 ----------------

    def _apply_level(self, data: dict, target: str, only_deepseek: bool) -> list:
        """把 target 写进各 provider 的 custom_extra_body。

        返回真正被改动的 provider id 列表（原本就一样的不算）。
        """
        changed = []
        for p in data.get("provider", []):
            pid = str(p.get("id", "?"))
            if only_deepseek and not pid.lower().startswith("deepseek"):
                continue

            old_body = p.get("custom_extra_body")
            if not isinstance(old_body, dict):
                old_body = {}

            new_body = dict(old_body)

            if target == "off":
                # 两条路一起堵：拿掉 effort，再显式把 thinking 关掉
                new_body.pop("reasoning_effort", None)
                new_body["thinking"] = {"type": "disabled"}
            else:
                new_body["reasoning_effort"] = target
                # 清掉可能残留的 thinking.disabled，不然会把 effort 盖掉
                new_body.pop("thinking", None)

            if new_body == old_body:
                continue

            p["custom_extra_body"] = new_body
            changed.append(pid)

        return changed

    # ---------------- 文件读写 ----------------

    def _load(self) -> dict:
        with open(self.cfg_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        tmp = self.cfg_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 先写临时文件再替换，避免写一半断电把配置写坏
        tmp.replace(self.cfg_path)

    def _backup(self) -> str:
        """备份配置文件，并只保留最近 N 份（默认 3）。

        超过上限时，把最旧的那份删掉——不是留着不管，
        否则每改一次档就多一个文件，迟早堆满。
        """
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = self.cfg_path.parent / f"cmd_config.json.bak_effort_{stamp}"
        shutil.copy2(self.cfg_path, bak)

        try:
            keep = int(self.config.get("max_backups", 3))
        except Exception:
            keep = 3
        if keep < 1:
            keep = 1

        removed = []
        try:
            olds = sorted(
                self.cfg_path.parent.glob("cmd_config.json.bak_effort_*"),
                key=lambda p: (p.stat().st_mtime, p.name),
            )
            while len(olds) > keep:
                old = olds.pop(0)
                if old == bak:
                    continue
                name = old.name
                old.unlink()
                removed.append(name)
        except Exception as e:
            logger.warning(f"[思考强度] 清理旧备份失败：{e}")

        if removed and self.config.get("verbose", True):
            logger.info(f"[思考强度] 清理旧备份 {len(removed)} 份：{', '.join(removed)}")

        return bak.name

    @staticmethod
    def _current_value(p: dict) -> str:
        """读一个 provider 现在是什么档。"""
        body = p.get("custom_extra_body") or {}
        t = body.get("thinking")
        if isinstance(t, dict) and str(t.get("type", "")).lower() == "disabled":
            return "off"
        v = body.get("reasoning_effort")
        # 旧版遗留的 minimal / medium 归到新档位上显示
        if isinstance(v, str):
            return LEVELS.get(v.lower(), v)
        return "none"

    def _current_counts(self, data: dict) -> dict:
        counts: dict[str, list[str]] = {}
        for p in data.get("provider", []):
            val = self._current_value(p)
            counts.setdefault(val, []).append(str(p.get("id", "?")))
        return counts

    # ---------------- 指令 ----------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("思考")
    async def cmd_thinking(self, event: AstrMessageEvent):
        """查看或修改思考强度"""
        raw = (event.message_str or "").strip()

        # 有些平台/插件会往消息文本里塞方括号标记，例如 [MSG_ID:1234567890]。
        # 别的实例上就是这样："/思考" 被读成 "不认识 [MSG_ID:...]"。
        # 所以先把这类标记整段抹掉，再解析参数。
        # 限长 64 字符，免得把正常内容里带方括号的句子误伤。
        raw = re.sub(r"\[[^\[\]]{0,64}\]", " ", raw).strip()
        raw = re.sub(r"\s+", " ", raw).strip()

        # message_str 可能带也可能不带指令前缀，两种都处理
        arg = raw
        for prefix in ("/思考", "思考"):
            if arg.startswith(prefix):
                arg = arg[len(prefix):]
                break
        arg = arg.strip()

        # 没参数 → 报告当前状态
        if not arg:
            if not self.cfg_path.exists():
                yield event.plain_result(f"找不到配置文件：{self.cfg_path}")
                return
            try:
                data = self._load()
            except Exception as e:
                yield event.plain_result(f"读配置失败：{e}")
                return

            counts = self._current_counts(data)
            lines = ["当前思考强度："]
            for val, ids in sorted(counts.items()):
                lines.append(f"  {DISPLAY.get(val, val)}")
                lines.append(f"      ← {', '.join(ids)}")
            lines.append("")
            lines.append("换档：/思考 关、/思考 低、/思考 高、/思考 最高")
            yield event.plain_result("\n".join(lines))
            return

        # 有参数 → 换档
        key = arg.lower()
        if key not in LEVELS:
            yield event.plain_result(f"不认识「{arg}」。\n\n{USAGE}")
            return

        target = LEVELS[key]

        if not self.cfg_path.exists():
            yield event.plain_result(f"找不到配置文件：{self.cfg_path}")
            return

        try:
            data = self._load()
        except Exception as e:
            yield event.plain_result(f"读配置失败：{e}")
            return

        bak_name = None
        if self.config.get("backup", True):
            try:
                bak_name = self._backup()
            except Exception as e:
                yield event.plain_result(f"备份失败，为安全起见不修改：{e}")
                return

        only_ds = bool(self.config.get("only_deepseek", True))
        changed = self._apply_level(data, target, only_ds)

        if not changed:
            yield event.plain_result(
                f"已经是「{DISPLAY.get(target, target)}」了，没有改动。"
            )
            return

        try:
            self._save(data)
        except Exception as e:
            yield event.plain_result(f"写配置失败：{e}\n备份还留着：{bak_name}")
            return

        logger.info(f"[思考强度] 改为 {target}，共 {len(changed)} 个 provider")

        note = f"备份：{bak_name}\n" if bak_name else "（未备份）\n"
        scope = "仅 DeepSeek" if only_ds else "全部 provider"
        yield event.plain_result(
            f"已改成「{DISPLAY.get(target, target)}」，共 {len(changed)} 个 provider（{scope}）。\n"
            f"{note}\n"
            "重启实例后生效。"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("思考档")
    async def cmd_levels(self, event: AstrMessageEvent):
        """列出可用档位"""
        yield event.plain_result(
            "可用档位（跟 DeepSeek 原生对齐）：\n"
            "  关 off     不思考，最快。简单问答用\n"
            "  低 low     轻度思考\n"
            "  高 high    默认档，日常和写代码都够\n"
            "  最高 max   投入最大算力，硬核推理用"
        )

#I Love You 沐