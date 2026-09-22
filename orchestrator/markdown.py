"""Render Markdown into Telegram HTML message chunks."""

from __future__ import annotations

import html
import re


class MarkdownRenderer:
    """Turns model Markdown into Telegram HTML chunks that stay inside the message limit."""

    def inline_to_html(self, text: str) -> str:
        """Converts inline Markdown (bold, italic, code, links, headings) to Telegram HTML."""
        # Protect inline code spans from further processing / escaping.
        inline_code: list[str] = []

        def _stash_inline_code(match: "re.Match[str]") -> str:
            inline_code.append(f"<code>{html.escape(match.group(1))}</code>")
            return f"\x00IC{len(inline_code) - 1}\x00"

        text = re.sub(r"`([^`\n]+)`", _stash_inline_code, text)

        # Escape everything else so raw HTML in the model output can't break parsing.
        text = html.escape(text)

        # Links: [label](https://url) — the URL is already HTML-escaped by the step above.
        text = re.sub(
            r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
            lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
            text,
        )

        # Bold: **text** or __text__
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
        text = re.sub(r"(?<!_)__(.+?)__(?!_)", r"<b>\1</b>", text, flags=re.DOTALL)

        # Strikethrough: ~~text~~
        text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.DOTALL)

        # Italic: *text* / _text_ (single markers, not bullet lists or bold leftovers)
        text = re.sub(r"(?<![\*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\*\w])", r"<i>\1</i>", text)
        text = re.sub(r"(?<![_\w])_(?!\s)([^_\n]+?)(?<!\s)_(?![_\w])", r"<i>\1</i>", text)

        # Headings (# .. ######) become bold lines.
        text = re.sub(r"(?m)^\s*#{1,6}\s+(.+?)\s*$", r"<b>\1</b>", text)

        # Restore inline code spans.
        text = re.sub(r"\x00IC(\d+)\x00", lambda m: inline_code[int(m.group(1))], text)
        return text

    def split_blocks(self, text: str) -> list[tuple[str, str, str]]:
        """Splits Markdown into ordered (kind, language, content) blocks.

        kind is either "code" (fenced block) or "text". language is only set for code.
        """
        blocks: list[tuple[str, str, str]] = []
        fence_re = re.compile(r"```([^\n`]*)\n?(.*?)```", re.DOTALL)
        pos = 0
        for match in fence_re.finditer(text):
            if match.start() > pos:
                blocks.append(("text", "", text[pos:match.start()]))
            lang = match.group(1).strip()
            code = match.group(2)
            if code.endswith("\n"):
                code = code[:-1]
            blocks.append(("code", lang, code))
            pos = match.end()
        if pos < len(text):
            blocks.append(("text", "", text[pos:]))
        return blocks

    def render(self, text: str, max_len: int = 3800) -> list[str]:
        """Renders Markdown into Telegram-HTML message chunks with code syntax highlighting.

        Fenced code blocks become <pre><code class="language-..."> so Telegram applies
        syntax highlighting. Each returned chunk is self-contained, well-formed HTML that
        fits within max_len, and code blocks are never split across a tag boundary.
        """
        messages: list[str] = []
        buffer = ""

        def flush() -> None:
            nonlocal buffer
            if buffer:
                messages.append(buffer)
                buffer = ""

        def push(segment: str) -> None:
            nonlocal buffer
            if not segment:
                return
            if not buffer:
                buffer = segment
            elif len(buffer) + 1 + len(segment) <= max_len:
                buffer = f"{buffer}\n{segment}"
            else:
                flush()
                buffer = segment

        for kind, lang, content in self.split_blocks(text):
            if kind == "code":
                opener = f'<pre><code class="language-{html.escape(lang)}">' if lang else "<pre>"
                closer = "</code></pre>" if lang else "</pre>"
                escaped = html.escape(content)
                if len(opener) + len(escaped) + len(closer) <= max_len:
                    push(f"{opener}{escaped}{closer}")
                    continue
                # Code block too large: split by lines, re-wrapping each chunk.
                flush()
                budget = max(1, max_len - len(opener) - len(closer))
                current = ""
                for line in escaped.split("\n"):
                    while len(line) > budget:
                        if current:
                            messages.append(f"{opener}{current}{closer}")
                            current = ""
                        messages.append(f"{opener}{line[:budget]}{closer}")
                        line = line[budget:]
                    if current and len(current) + 1 + len(line) > budget:
                        messages.append(f"{opener}{current}{closer}")
                        current = ""
                    current = f"{current}\n{line}" if current else line
                if current:
                    push(f"{opener}{current}{closer}")
            else:
                html_text = self.inline_to_html(content)
                if len(html_text) <= max_len:
                    push(html_text)
                    continue
                # Text block too large: split on line boundaries to keep inline tags intact.
                flush()
                current = ""
                for line in html_text.split("\n"):
                    if len(line) > max_len:
                        if current:
                            messages.append(current)
                            current = ""
                        for i in range(0, len(line), max_len):
                            messages.append(line[i:i + max_len])
                        continue
                    if current and len(current) + 1 + len(line) > max_len:
                        messages.append(current)
                        current = ""
                    current = f"{current}\n{line}" if current else line
                if current:
                    push(current)

        flush()
        return messages


markdown_renderer = MarkdownRenderer()
