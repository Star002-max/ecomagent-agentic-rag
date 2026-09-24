"""Public tool arguments only. Data stores and paths never enter the schema."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


DateText = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class ProductInput(BaseModel):
    """Identify one product; the service handles SKU normalization."""

    model_config = ConfigDict(extra="forbid", strict=True)
    sku: str = Field(min_length=1, max_length=32, description="商品编号，例如SKU001。")


class SalesInput(ProductInput):
    """An explicit inclusive sales window."""

    start_date: DateText = Field(description="开始日期YYYY-MM-DD，包含当天。")
    end_date: DateText = Field(description="结束日期YYYY-MM-DD，包含当天。")


class ComparisonInput(ProductInput):
    """Two explicit windows; ordering and completeness remain service rules."""

    current_start: DateText = Field(description="本期开始日期YYYY-MM-DD，包含当天。")
    current_end: DateText = Field(description="本期结束日期YYYY-MM-DD，包含当天。")
    previous_start: DateText = Field(description="前期开始日期YYYY-MM-DD，包含当天。")
    previous_end: DateText = Field(description="前期结束日期；必须早于本期开始日期。")


class InventoryInput(ProductInput):
    """Optional dates use the existing service's default 30-day window."""

    start_date: DateText | None = Field(
        default=None, description="可选开始日期；省略或null时为结束日前29天。"
    )
    end_date: DateText | None = Field(
        default=None, description="可选结束日期；省略或null时使用数据截止日，不是电脑当天。"
    )


class ReviewInput(InventoryInput):
    """Limit low-rating examples without changing the aggregate counts."""

    low_rating_limit: int = Field(
        default=5, ge=1, le=100,
        description="最多返回多少条最近低分评价（评分<=2），1至100的整数，默认5。",
    )
