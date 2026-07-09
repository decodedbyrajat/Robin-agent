---
name: apple-calendar
description: "Apple Calendar via osascript: list events today, date ranges, upcoming schedule."
version: 1.1.0
author: Robin Agent
license: MIT
platforms: [macos]
metadata:
  robin:
    tags: [Calendar, events, schedule, macOS, Apple, iCloud]
prerequisites:
  commands: [osascript]
---

# Apple Calendar

Use `osascript` (AppleScript) to read events from Apple Calendar. Works with all calendar types the user has added in Calendar.app (iCloud, Google, Exchange, local). No third-party tools needed — osascript ships with macOS.

> **Note:** icalBuddy is broken on macOS 26+ (uses a deprecated 2012 framework). Use the osascript patterns below instead.

## Prerequisites

- **macOS** with Calendar.app configured
- Calendar.app must be open (or have been opened at least once after granting permission)
- First run triggers a macOS permission dialog → allow in System Settings → Privacy & Security → Calendars

## When to Use

- User asks "what's on my calendar today / this week"
- User asks about upcoming events, meetings, or appointments
- Checking free/busy time before scheduling
- Listing all calendars the user has

## When NOT to Use

- Reminders/tasks → use `apple-reminders` skill (`remindctl`)
- Creating/editing events → use the create/update patterns below or direct user to Calendar.app
- Google Calendar API (invites, attendee management) → use Google Calendar MCP tools if available

## Quick Reference

### List All Calendars

```bash
osascript -e 'tell application "Calendar" to get name of every calendar'
```

### Today's Events

```bash
osascript << 'EOF'
set todayStart to (current date)
set time of todayStart to 0
set todayEnd to todayStart + 86399
set output to ""
tell application "Calendar"
    repeat with cal in every calendar
        repeat with evt in (every event of cal whose start date >= todayStart and start date <= todayEnd)
            set output to output & (name of cal) & " | " & (summary of evt) & " | " & (start date of evt) & " | " & (end date of evt) & return
        end repeat
    end repeat
end tell
return output
EOF
```

### Upcoming Events (Next N Days)

Replace `7 * days` with how many days ahead to look:

```bash
osascript << 'EOF'
set startDate to (current date)
set time of startDate to 0
set endDate to startDate + (7 * days)
set output to ""
tell application "Calendar"
    repeat with cal in every calendar
        repeat with evt in (every event of cal whose start date >= startDate and start date < endDate)
            set output to output & (name of cal) & " | " & (summary of evt) & " | " & (start date of evt) & " | " & (end date of evt) & return
        end repeat
    end repeat
end tell
return output
EOF
```

### Events in a Specific Date Range

```bash
osascript << 'EOF'
set startDate to date "Monday, May 5, 2026 at 12:00:00 AM"
set endDate to date "Friday, May 9, 2026 at 11:59:59 PM"
set output to ""
tell application "Calendar"
    repeat with cal in every calendar
        repeat with evt in (every event of cal whose start date >= startDate and start date <= endDate)
            set output to output & (name of cal) & " | " & (summary of evt) & " | " & (start date of evt) & return
        end repeat
    end repeat
end tell
return output
EOF
```

### Create an Event

```bash
osascript << 'EOF'
set startDate to date "Monday, May 5, 2026 at 2:00:00 PM"
set endDate to date "Monday, May 5, 2026 at 3:00:00 PM"
tell application "Calendar"
    tell calendar "Work"
        make new event with properties {summary:"Team Standup", start date:startDate, end date:endDate}
    end tell
end tell
EOF
```

### Delete an Event by Name (on a date)

```bash
osascript << 'EOF'
set targetDate to date "Monday, May 5, 2026 at 12:00:00 AM"
tell application "Calendar"
    tell calendar "Work"
        set matches to (every event whose summary is "Team Standup" and start date >= targetDate)
        repeat with evt in matches
            delete evt
        end repeat
    end tell
end tell
EOF
```

## Ensure Calendar.app Is Running (Required)

If `osascript` returns empty or errors, Calendar.app needs to be open:

```bash
open -a Calendar && sleep 2
# then run your osascript command
```

## Rules

1. Always `open -a Calendar` if osascript returns empty output — the app must be running for EventKit to serve data
2. Use `every event whose start date >= X and start date < Y` — this is more reliable than `contains` filters
3. When creating events, confirm the calendar name with the user first (use "list all calendars" above)
4. Pipe multi-line heredoc commands through `osascript << 'EOF' ... EOF` — the one-liner `-e` form struggles with multi-statement scripts
5. Format dates as `date "Weekday, Month Day, Year at H:MM:SS AM/PM"` for AppleScript date literals
