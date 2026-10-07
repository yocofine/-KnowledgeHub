"""Preserve the legacy rule renderer; never expose webhook URLs in errors."""
import base64
import hashlib
import hmac
import html
import re
import time
from urllib.parse import quote_plus, urlsplit
import httpx

TAG_RE = re.compile(r"<[^>]+>")
FONT_TAG_RE = re.compile(r'<font\s+color="[^"]*"\s*>|</font>', re.I)
SPAN_RE = re.compile(r'<span[^>]*style="(?P<style>[^"]*)"[^>]*>(?P<text>.*?)</span>', re.I | re.S)


def color(raw):
    value = raw.strip().lower()
    rgb = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", value)
    if rgb:
        return "#%02X%02X%02X" % tuple(min(255, int(x)) for x in rgb.groups())
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        return ("#" + "".join(x * 2 for x in value[1:])).upper()
    return value.upper()


def span(match):
    style, text = match.group("style"), match.group("text")
    if re.search(r"font-weight:\s*(?:bold|[6-9]00)", style, re.I):
        text = f" **{text.strip()}** "
    if re.search(r"font-style:\s*italic", style, re.I):
        text = f" *{text.strip()}* "
    match_color = re.search(r"(?:^|;)\s*color:\s*(#[0-9a-fA-F]{3,6}|rgb\([^)]*\))", style)
    if match_color:
        text = f'<font color="{color(match_color.group(1))}">{text}</font>'
    return text


def rich_text(value):
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>|</(?:p|div|li|h[1-6])\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<(?:p|div|li|h[1-6])(?:\s+[^>]*)?>", "", text, flags=re.I)
    text = SPAN_RE.sub(span, text)
    text = re.sub(r"</?(?:b|strong)\s*>", " ** ", text, flags=re.I)
    text = re.sub(r"</?(?:i|em)\s*>", " * ", text, flags=re.I)
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: f" **{m.group(1).strip()}** ", text, flags=re.S)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", lambda m: f" *{m.group(1).strip()}* ", text, flags=re.S)
    kept = []
    def keep(match):
        kept.append(match.group(0))
        return f"\ue000{len(kept)-1}\ue001"
    text = FONT_TAG_RE.sub(keep, text)
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"\ue000(\d+)\ue001", lambda m: kept[int(m.group(1))], text)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def valid_webhook(value):
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and parsed.hostname == "oapi.dingtalk.com"
            and parsed.path == "/robot/send" and not parsed.username and not parsed.password and not parsed.fragment)


async def send(rule, config):
    webhook = config.get("webhook", "")
    if not config.get("enabled") or not valid_webhook(webhook):
        raise ValueError("未配置有效的钉钉机器人")
    secret = config.get("secret", "")
    if secret:
        timestamp = str(int(time.time() * 1000))
        digest = hmac.new(secret.encode(), f"{timestamp}\n{secret}".encode(), hashlib.sha256).digest()
        separator = "&" if "?" in webhook else "?"
        webhook += f"{separator}timestamp={timestamp}&sign={quote_plus(base64.b64encode(digest).decode())}"
    text = (f"### 规则通知｜{rule['title']}\n\n{rich_text(rule['content'])[:3500]}\n\n"
            f"分组：{rule['group_name']}" + (f"\n\n标签：{rule['tags']}" if rule.get('tags') else '') + f"\n\n发布人：{rule['operator']}")
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        result = await client.post(webhook, json={"msgtype": "markdown", "markdown": {"title": rule["title"], "text": text}})
    if result.status_code != 200 or result.json().get("errcode", 0) != 0:
        raise ValueError("钉钉推送失败，请检查机器人配置及安全设置")
