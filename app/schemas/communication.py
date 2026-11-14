"""Validated weekly schedules, country/timezone pairs and client-specific closures."""
from datetime import date
from pydantic import BaseModel, Field, model_validator


class WorkPeriod(BaseModel):
    start: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    end: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')


class Closure(BaseModel):
    start: date
    end: date
    name: str = Field(min_length=1, max_length=120)

    @model_validator(mode='after')
    def valid_range(self):
        if self.end < self.start or (self.end-self.start).days > 366:
            raise ValueError('休假结束日期应不早于开始日期，且不超过 367 天。')
        if not self.name.strip():
            raise ValueError('请填写休假说明。')
        self.name = self.name.strip()
        return self


class Schedule(BaseModel):
    weekdays: list[int] = Field(default_factory=lambda: [0,1,2,3,4], max_length=7)
    periods: list[WorkPeriod] = Field(default_factory=lambda: [WorkPeriod(start='09:00',end='12:00'),WorkPeriod(start='13:00',end='17:00')], max_length=4)

    @model_validator(mode='after')
    def validate_intervals(self):
        if any(day not in range(7) for day in self.weekdays) or len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError('工作日必须是周一至周日，且不能重复。')
        if self.weekdays and not self.periods:
            raise ValueError('请至少填写一个工作时段。')
        spans=[]
        for day in self.weekdays:
            for period in self.periods:
                start=day*1440+minute(period.start);end=day*1440+minute(period.end)
                if end==start:raise ValueError('开始和结束时间不能相同。')
                if end<start:end+=1440
                if end>10080:spans.extend([(start,10080),(0,end-10080)])
                else:spans.append((start,end))
        spans.sort()
        if any(current[0]<previous[1] for previous,current in zip(spans,spans[1:])):
            raise ValueError('工作时段不能重叠，请检查跨日时段。')
        return self


def minute(value):
    hour,minutes=map(int,value.split(':'));return hour*60+minutes


class PlaceConfig(BaseModel):
    country: str = Field(pattern=r'^[A-Z]{2}$')
    timezone: str = Field(min_length=1,max_length=100)
    city: str = Field(default='',max_length=100)
    subdivision: str | None = Field(default=None,max_length=30)
    schedule: Schedule = Field(default_factory=Schedule)
    closures: list[Closure] = Field(default_factory=list,max_length=20)
    confirmed: bool = False
    respect_public_holidays: bool = True


class Preferences(BaseModel):
    favorites: list[str] = Field(default_factory=list,max_length=30)
    overrides: dict[str,PlaceConfig] = Field(default_factory=dict,max_length=40)
    home_timezone: str = Field(default='Asia/Shanghai',max_length=100)
    home_schedule: Schedule = Field(default_factory=lambda: Schedule(periods=[WorkPeriod(start='09:00',end='12:00'),WorkPeriod(start='13:00',end='18:00')]))
