from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Config(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    dataset_id: str = Field(pattern=r'^[a-f0-9]{16}$')
    start: str
    end: str
    training_end: str
    side: Literal['buy', 'sell'] = 'buy'
    quantity: float = Field(default=500, gt=0, le=1e9)
    participation: float = Field(default=0.10, gt=0, le=0.5)
    max_participation: float = Field(default=0.20, gt=0, le=0.5)
    fee_bps: float = Field(default=1, ge=0, le=100)
    assumed_spread_bps: float = Field(default=2, ge=0, le=200)
    impact_bps: float = Field(default=5, ge=0, le=200)
    noise_bps: float = Field(default=0.5, ge=0, le=100)
    seed: int = Field(default=42, ge=0, le=2**32-1)
    quote_max_age_seconds: int = Field(default=120, ge=1, le=3600)

    @model_validator(mode='after')
    def participation_limit(self):
        if self.participation > self.max_participation:
            raise ValueError('POV participation cannot exceed the execution capacity cap')
        return self

class ImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    trades_csv: str = Field(max_length=8_000_000)
    quotes_csv: str | None = Field(default=None, max_length=4_000_000)
    description: str = Field(default='User-supplied historical data; provenance not independently verified.', max_length=1000)

class BatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    config: Config
    windows: list[dict[str, str]] = Field(min_length=2, max_length=12)
