from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class PostRecord:
    author_name: str
    post_content: str
    post_link: str
    post_time: str
    group_link: str
