import { useEffect, useMemo, useRef, useState } from "react";
import "./DeadlineDateTimePicker.css";

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];

function pad(value) {
  return String(value).padStart(2, "0");
}

function toLocalValue(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function parseLocalValue(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function startOfDay(date) {
  const next = new Date(date);
  next.setHours(0, 0, 0, 0);
  return next;
}

function isSameDay(a, b) {
  return a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function formatDisplay(value) {
  const date = parseLocalValue(value);
  if (!date) return "選擇截止日期與時間";
  return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function buildCalendarDays(monthDate) {
  const first = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());

  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

export default function DeadlineDateTimePicker({ id, value, min, onChange, className = "", compact = false }) {
  const rootRef = useRef(null);
  const minDate = useMemo(() => parseLocalValue(min) || new Date(), [min]);
  const selectedDate = parseLocalValue(value);
  const fallbackDate = selectedDate && selectedDate >= minDate ? selectedDate : minDate;
  const [isOpen, setIsOpen] = useState(false);
  const [viewDate, setViewDate] = useState(() => new Date(fallbackDate.getFullYear(), fallbackDate.getMonth(), 1));

  useEffect(() => {
    const handlePointerDown = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setIsOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    setViewDate(new Date(fallbackDate.getFullYear(), fallbackDate.getMonth(), 1));
  }, [fallbackDate, isOpen]);

  const calendarDays = useMemo(() => buildCalendarDays(viewDate), [viewDate]);
  const activeDate = selectedDate || fallbackDate;
  const activeHour = activeDate.getHours();
  const activeMinute = activeDate.getMinutes();

  const emitDate = (date) => {
    if (date < minDate) {
      onChange(toLocalValue(minDate));
      return;
    }
    onChange(toLocalValue(date));
  };

  const handleSelectDay = (day) => {
    const next = new Date(day);
    next.setHours(activeHour, activeMinute, 0, 0);
    if (next < minDate) {
      next.setHours(minDate.getHours(), minDate.getMinutes(), 0, 0);
    }
    emitDate(next);
  };

  const handleSelectHour = (hour) => {
    const next = new Date(activeDate);
    next.setHours(hour, activeMinute, 0, 0);
    emitDate(next);
  };

  const handleSelectMinute = (minute) => {
    const next = new Date(activeDate);
    next.setMinutes(minute, 0, 0);
    emitDate(next);
  };

  const monthLabel = `${viewDate.getFullYear()}年${pad(viewDate.getMonth() + 1)}月`;
  const prevMonth = new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1);
  const prevMonthDisabled = new Date(prevMonth.getFullYear(), prevMonth.getMonth() + 1, 0) < startOfDay(minDate);

  return (
    <div ref={rootRef} className={`deadline-picker ${compact ? "deadline-picker-compact" : ""} ${className}`}>
      <button
        id={id}
        type="button"
        className="deadline-picker-trigger"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
      >
        <span>{formatDisplay(value)}</span>
        <i className="ri-calendar-line"></i>
      </button>

      {isOpen && (
        <div className="deadline-picker-popover" role="dialog" aria-label="選擇截止日期與時間">
          <div className="deadline-picker-calendar">
            <div className="deadline-picker-header">
              <button type="button" className="deadline-picker-icon-btn" disabled={prevMonthDisabled} onClick={() => setViewDate(prevMonth)}>
                <i className="ri-arrow-left-s-line"></i>
              </button>
              <span>{monthLabel}</span>
              <button type="button" className="deadline-picker-icon-btn" onClick={() => setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1))}>
                <i className="ri-arrow-right-s-line"></i>
              </button>
            </div>
            <div className="deadline-picker-weekdays">
              {WEEKDAYS.map((weekday) => <span key={weekday}>{weekday}</span>)}
            </div>
            <div className="deadline-picker-days">
              {calendarDays.map((day) => {
                const disabled = startOfDay(day) < startOfDay(minDate);
                const muted = day.getMonth() !== viewDate.getMonth();
                const selected = isSameDay(day, selectedDate);
                const today = isSameDay(day, new Date());
                return (
                  <button
                    type="button"
                    key={day.toISOString()}
                    className={`${muted ? "muted" : ""} ${selected ? "selected" : ""} ${today ? "today" : ""}`}
                    disabled={disabled}
                    onClick={() => handleSelectDay(day)}
                  >
                    {day.getDate()}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="deadline-picker-time">
            <div className="deadline-picker-time-title">
              <i className="ri-time-line"></i>
              <span>{pad(activeHour)}:{pad(activeMinute)}</span>
            </div>
            <div className="deadline-picker-time-columns">
              <div className="deadline-picker-time-group">
                <div className="deadline-picker-time-label">時</div>
                <div className="deadline-picker-time-column" aria-label="選擇小時">
                  {Array.from({ length: 24 }, (_, hour) => {
                    const candidate = new Date(activeDate);
                    candidate.setHours(hour, activeMinute, 0, 0);
                    return (
                      <button type="button" key={hour} className={hour === activeHour ? "selected" : ""} disabled={candidate < minDate} onClick={() => handleSelectHour(hour)}>
                        {pad(hour)}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="deadline-picker-time-group">
                <div className="deadline-picker-time-label">分</div>
                <div className="deadline-picker-time-column" aria-label="選擇分鐘">
                  {Array.from({ length: 60 }, (_, minute) => {
                    const candidate = new Date(activeDate);
                    candidate.setMinutes(minute, 0, 0);
                    return (
                      <button type="button" key={minute} className={minute === activeMinute ? "selected" : ""} disabled={candidate < minDate} onClick={() => handleSelectMinute(minute)}>
                        {pad(minute)}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
