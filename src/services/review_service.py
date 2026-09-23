"""Review-event aggregation; no assumption that every day has a review."""

from datetime import timedelta

import pandas as pd

from .common import base_result, default_window, records, window
from .data_loader import CsvDataStore


def summarize_reviews(frame: pd.DataFrame) -> dict:
    """Average individual events rather than averaging precomputed daily means."""
    return {"review_count": len(frame),
            "average_rating": float(frame["rating"].mean()) if len(frame) else None,
            "low_rating_count": int(frame["rating"].le(2).sum())}


def get_review_data(store: CsvDataStore, sku: str,
                    start_date: str | None = None, end_date: str | None = None,
                    low_rating_limit: int = 5) -> dict:
    """Return event-weighted ratings and preceding equal-length comparison.

    Low rating means <=2. Return the most recent N such events, with counts
    and truncation disclosed. Sparse days are not automatically data errors.
    """
    if isinstance(low_rating_limit, bool) or not isinstance(low_rating_limit, int) or not (
        1 <= low_rating_limit <= 100
    ):
        raise ValueError("low_rating_limit必须是1至100的整数。")
    start, end = default_window(store, start_date, end_date)
    result = base_result(store, sku)
    result.update(start_date=start.isoformat(), end_date=end.isoformat(), metrics=None,
                  previous=None, rating_change=None, low_rating_reviews=[])
    if result["status"] == "not_found":
        return result
    all_reviews = store.table("reviews")
    frame = window(all_reviews, result["sku"], start, end)
    previous_end = start - timedelta(days=1)
    previous_start = start - timedelta(days=(end - start).days + 1)
    old = window(all_reviews, result["sku"], previous_start, previous_end)
    # Event absence cannot prove ingestion completeness. Expose the observed
    # source span and suppress comparisons extending outside it.
    source_start = all_reviews["date"].min().date() if len(all_reviews) else None
    source_end = all_reviews["date"].max().date() if len(all_reviews) else None
    in_span = source_start is not None and source_start <= start <= end <= source_end
    previous_in_span = (source_start is not None and
                        source_start <= previous_start <= previous_end <= source_end)
    result.update(status="no_data" if frame.empty else "ok" if in_span else "partial",
                  metrics=summarize_reviews(frame), source="reviews.csv",
                  observed_source_start=source_start.isoformat() if source_start else None,
                  observed_source_end=source_end.isoformat() if source_end else None,
                  within_observed_source_span=in_span)
    result["previous"] = {
        "start_date": previous_start.isoformat(), "end_date": previous_end.isoformat(),
        "metrics": summarize_reviews(old), "within_observed_source_span": previous_in_span,
    }
    comparable = in_span and previous_in_span and not frame.empty and not old.empty
    result["comparison_status"] = "ok" if comparable else "insufficient_data"
    if comparable:
        result["rating_change"] = (
            result["metrics"]["average_rating"] - result["previous"]["metrics"]["average_rating"]
        )
    low = frame[frame["rating"].le(2)].sort_values("date", ascending=False, kind="stable")
    result["low_rating_reviews"] = records(low.head(low_rating_limit))
    result["low_rating_reviews_truncated"] = len(low) > low_rating_limit
    result["message"] = {"ok": "", "no_data": "当前区间没有评价记录。",
                         "partial": "请求区间超出评价数据已观测日期范围。"}[result["status"]]
    result["limitations"] = ["按已有评价记录统计；没有评价不等于零分，也不能据此证明采集完整。"]
    return result
