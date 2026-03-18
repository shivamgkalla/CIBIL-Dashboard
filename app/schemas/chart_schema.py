"""Generic chart-ready schemas."""

from pydantic import BaseModel, Field


class ChartPoint(BaseModel):
    """Single chart point with x-axis label and y-axis value."""

    x: str = Field(..., description="X-axis value (typically a date string).")
    y: int | float | str = Field(..., description="Y-axis value.")

