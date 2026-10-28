"""Public, read-only Jellyfin telemetry. No credentials or media titles."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

type State = Literal['warming_up', 'ready', 'not_configured', 'unauthorized', 'unavailable']


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)


class LibraryCounts(StrictModel):
    state: State
    updated_at: float | None = Field(ge=0)
    values: dict[str, int | None]

    @model_validator(mode='after')
    def validate_counts(self) -> LibraryCounts:
        fields = {'MovieCount','SeriesCount','EpisodeCount','SongCount','AlbumCount','ArtistCount',
                  'MusicVideoCount','BookCount','BoxSetCount','TrailerCount','ProgramCount'}
        if set(self.values) != fields:
            raise ValueError('Unexpected count fields')
        if any(v is not None and (type(v) is not int or not 0 <= v <= 2**53-1) for v in self.values.values()):
            raise ValueError('Invalid count')
        if self.state == 'ready' and (self.updated_at is None or any(self.values[k] is None for k in ('MovieCount','SeriesCount','EpisodeCount'))):
            raise ValueError('Incomplete library counts')
        return self


class MediaStorage(StrictModel):
    state: State
    updated_at: float | None = Field(ge=0)
    used_bytes: int | None = Field(ge=0)


class MediaDrive(StrictModel):
    state: State
    updated_at: float | None = Field(ge=0)
    total_bytes: int | None = Field(ge=0)
    free_bytes: int | None = Field(ge=0)


class JellyfinSnapshot(StrictModel):
    ok: Literal[True]
    counts: LibraryCounts
    storage: MediaStorage
    drive: MediaDrive
    media_path: Literal['/srv/data/media']
    count_refresh_seconds: Literal[300]
    storage_refresh_seconds: Literal[300]
