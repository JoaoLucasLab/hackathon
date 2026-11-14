# Demo script: conversational planner (AI-08)

The demo path with `FEATURE_CONVERSATIONAL_PLANNER=true` on the backend and
`VITE_FEATURE_CONVERSATIONAL_PLANNER=true` on the frontend build. Both flags must be on;
with either off, the app runs the old 3-card flow.

Run it on the demo snapshot (`make restore-snapshot`), so the schedules are the same
every time. The classes and times named below come from that snapshot; if the data
was refreshed, read them off the card instead.

## Before you start

- Open the app in a fresh private window (no old session cookie).
- Check that the nav shows **Plan**, **My plan** and **Professors**. If it shows
  **Schedules**, the frontend was built with the flag off.

## The path

| # | Who does what | What the audience sees | If it goes wrong |
| --- | --- | --- | --- |
| 1 | Open the app. Click **Try the sample audit**. | The consent screen. | Reload. |
| 2 | Check the box, click **Use sample audit**, then **Plan my schedule**. | "What you still need", then the planner chat. | Click **Use sample audit** again. |
| 3 | Type: `Help me plan my semester` | The assistant asks for the credit load (the track comes from the audit). No schedule yet. | If it builds right away, the backend flag is off. |
| 4 | Type: `12 to 15 credits, campus classes only, done by 2:00 PM` | It may ask one more question (courses to include or skip, or days off). | Answer `No preference`. |
| 5 | Answer any remaining question with the quick reply (`No preference` / `None`). | A short list of the preferences and "Should I build a schedule with these?" | Type `Build it`. |
| 6 | Click **Build it**. | **Option 1** appears inside the chat: week calendar, each class with the requirement it fills, professors with a star and a Rate My Professors link, seats as of a time, "Confirm with BYU-Idaho Academic Advising." Then "Does this schedule work for you?" with **This works** and **Change something**. | If no card appears, check that the frontend flag is on. |
| 7 | Point out a Friday class on the calendar. Click **Change something** (the cursor jumps to the message box) and type: `no Fridays` | One or two sentences on what changed (for example, a class dropped or moved). **Option 2** appears. Option 1 collapses to one line, such as "Option 1: 15 credits, MTWRF, not chosen". | If the assistant asks what to change, type `no classes on Friday`. |
| 8 | Optional: click the Option 1 line to show it is still there, then collapse it. | Option 1 opens again. | Skip it. |
| 9 | Click **This works**. | "Saved as your Winter 2027 plan. This does not register you for classes. Confirm with BYU-Idaho Academic Advising." Option 2 shows a **Confirmed** label. | Type `This works`. |
| 10 | Click **My plan** in the nav. | The confirmed schedule, read-only, with calendar and class details. | Reload: the plan is kept for the session. |
| 11 | Optional: reload the page and go back to **Plan**. | The conversation and both cards are still there. | Skip it. |

## What to say

- "It asks before it builds: it only needs what the audit does not already say."
- "One schedule at a time, inside the conversation. Every fact on the card comes from
  our solver, not from the model."
- "A schedule the student rejects never comes back."
- "Confirming saves a plan. It does not register anyone. The student still confirms
  with Academic Advising."

## Keyboard-only run

Every step works without a mouse: Tab to the message box, quick replies, the card's
class rows and backup sections, **This works**, **Change something**, the collapsed
card lines (Enter opens them), and the **My plan** link.
