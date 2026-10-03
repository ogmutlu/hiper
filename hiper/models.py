"""Typed records at the CSV/domain boundary; existing CSV formats stay stable."""

import datetime as dt
from typing import TypedDict


class Session(TypedDict):
    id: str
    title: str
    start: dt.datetime
    end: dt.datetime
    duration: int
    comment: str


class Goal(TypedDict):
    title: str
    estimate_seconds: int
    estimate_formatted: str
    estimate_timestamp: dt.datetime | None
    deadline: dt.date | None
    time_worked_seconds: int
    time_worked_formatted: str
    start_by: dt.date | None


class GoalSummary(TypedDict):
    title: str
    estimate_seconds: int
    estimate: str
    time_worked_seconds: int
    time_worked: str
    remaining: str
    deadline: dt.date | None
    start_by: dt.date | None


class Book(TypedDict):
    title: str
    length: int
    current_page: int
    time_per_page_seconds: int


class LogEntry(TypedDict):
    id: str
    message: str
    timestamp: dt.datetime | None


class Habit(TypedDict):
    name: str
    frequency: str
    created_at: dt.datetime
