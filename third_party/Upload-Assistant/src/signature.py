from __future__ import annotations

from typing import Optional, Dict, Any


def _format_size_tag(text: str, size: Optional[int]) -> str:
    if not text:
        return ""
    if size is None or size <= 0:
        return text
    return f"[size={size}]{text}[/size]"


def build_signature(meta: Dict[str, Any], style: str = "center", size: Optional[int] = 10) -> str:
    """
    Build a signature block based on metadata and requested style.

    Styles:
        - "right": wraps content with [right]..[/right]
        - "align-right": wraps with [align=right]..[/align]
        - "center": wraps with [center]..[/center]
        - "plain": no wrapper, just the content
        - "html-right": returns HTML formatted signature (for trackers that use HTML)
    """
    text = (meta.get("ua_signature_text") or meta.get("ua_signature") or "").strip()
    subtext = (meta.get("ua_signature_subtext") or "").strip()
    link = (meta.get("ua_signature_link") or "").strip()
    avatar = (meta.get("uploader_avatar") or "").strip()

    if not (text or subtext or avatar):
        return ""

    if style.startswith("html"):
        blocks = []
        align = "center"
        size_px = size if size and size > 0 else 20
        if text:
            link_target = link or "#"
            blocks.append(
                f'<div style="text-align: {align}; font-size: {size_px}px;"><a href="{link_target}">{text}</a></div>'
            )
        if subtext:
            blocks.append(f'<div style="text-align: {align}; font-size: {size_px}px;">{subtext}</div>')
        if avatar:
            blocks.append(f'<div style="text-align: center;"><img src="{avatar}" alt="Uploader avatar" style="max-height: 300px;"></div>')
        html_block = "\n".join(blocks)
        return html_block + ("\n" if html_block else "")

    main = ""
    normalized_size = size if size and size > 0 else None
    if text:
        main = _format_size_tag(text, normalized_size)
        if link:
            main = f"[url={link}]{main}[/url]"
    elif link:
        main = f"[url={link}]{_format_size_tag(link, normalized_size)}[/url]"

    lines = []
    if main:
        lines.append(main)
    if subtext:
        lines.append(_format_size_tag(subtext, normalized_size))

    wrapper_start = wrapper_end = ""
    if style == "right":
        wrapper_start, wrapper_end = "[right]", "[/right]"
    elif style == "align-right":
        wrapper_start, wrapper_end = "[align=right]", "[/align]"
    elif style == "center":
        wrapper_start, wrapper_end = "[center]", "[/center]"

    block = ""
    if lines:
        content = "\n".join(line for line in lines if line)
        if wrapper_start or wrapper_end:
            block = f"{wrapper_start}{content}{wrapper_end}"
        else:
            block = content

    avatar_block = ""
    if avatar:
        avatar_block = f"[center][img=300x300]{avatar}[/img][/center]"

    parts = [part for part in (block, avatar_block) if part]
    final_block = "\n".join(parts)
    if final_block and not final_block.endswith("\n"):
        final_block += "\n"
    return final_block
