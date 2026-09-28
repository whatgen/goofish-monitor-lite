"""Shared parsing for independent search phrases; spaces remain part of a phrase."""
import re


def search_terms(value: str) -> list[str]:
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError('搜索词格式有误，最多填写 2000 字')
    result, seen = [], set()
    for part in re.split(r'[,，\r\n]+', value):
        word = part.strip()
        if not word:
            continue
        if len(word) > 80:
            raise ValueError('每个搜索词最多 80 字')
        if word.casefold() not in seen:
            seen.add(word.casefold())
            result.append(word)
    if not 1 <= len(result) <= 20:
        raise ValueError('请填写 1 至 20 个搜索词，用逗号或换行分隔')
    return result
