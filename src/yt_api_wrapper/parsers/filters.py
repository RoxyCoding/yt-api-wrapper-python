"""Protobuf encoder for YouTube's ``sp`` search filter parameter."""

from __future__ import annotations

import base64
from typing import Sequence

from ..models import DurationFilter, FeatureFilter, SearchType, SortByFilter, UploadDateFilter

_SORT_VALUES: dict[str, int] = {"relevance": 0, "date": 1, "views": 2, "rating": 3}
_UPLOAD_VALUES: dict[str, int] = {"hour": 1, "today": 2, "week": 3, "month": 4, "year": 5}
_TYPE_VALUES: dict[str, int] = {"video": 1, "channel": 2, "playlist": 3, "movie": 4}
_DURATION_VALUES: dict[str, int] = {"short": 1, "medium": 3, "long": 2}
_FEATURE_FIELDS: dict[str, int] = {
    "hd": 4,
    "subtitles": 5,
    "creativeCommons": 6,
    "4k": 14,
    "live": 8,
    "360": 15,
    "hdr": 25,
    "vr180": 26,
}


def encode_search_filters(
    *,
    type: SearchType | None = None,
    upload_date: UploadDateFilter | None = None,
    duration: DurationFilter | None = None,
    sort_by: SortByFilter | None = None,
    features: Sequence[FeatureFilter] | None = None,
) -> str | None:
    """Encode search filter options into YouTube's base64url ``sp`` protobuf parameter.

    Layout (field numbers from the searchFilter message):
      1: sortBy (varint, top level)
      2: filters submessage
        1 uploadDate, 2 type, 3 duration,
        4 hd, 5 subtitles, 6 creativeCommons, 8 live, 14 4k, 15 360, 25 hdr, 26 vr180
    """
    filters: list[int] = []
    if upload_date and upload_date in _UPLOAD_VALUES:
        filters.extend(_varint_field(1, _UPLOAD_VALUES[upload_date]))
    if type and type != "all" and type in _TYPE_VALUES:
        filters.extend(_varint_field(2, _TYPE_VALUES[type]))
    if duration and duration in _DURATION_VALUES:
        filters.extend(_varint_field(3, _DURATION_VALUES[duration]))
    for feature in features or ():
        field_num = _FEATURE_FIELDS.get(feature)
        if field_num is not None:
            filters.extend(_varint_field(field_num, 1))

    message: list[int] = []
    if sort_by and sort_by != "relevance" and sort_by in _SORT_VALUES:
        message.extend(_varint_field(1, _SORT_VALUES[sort_by]))
    if filters:
        message.extend(_length_delimited_field(2, filters))

    if not message:
        return None
    return base64.urlsafe_b64encode(bytes(message)).decode("ascii").rstrip("=")


def _varint_field(field: int, value: int) -> list[int]:
    return [(field << 3) | 0, *_varint(value)]


def _length_delimited_field(field: int, payload: list[int]) -> list[int]:
    return [(field << 3) | 2, *_varint(len(payload)), *payload]


def _varint(value: int) -> list[int]:
    out: list[int] = []
    remaining = value
    while True:
        byte = remaining & 0x7F
        remaining >>= 7
        if remaining > 0:
            byte |= 0x80
        out.append(byte)
        if remaining == 0:
            break
    return out
