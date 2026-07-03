# Controller worked example — `ep01` / `task01`

What Alex's screen looks like for the **frog-throw fixture task**. Step text and clip order come from [fixtures/ep01-task01-results.json](fixtures/ep01-task01-results.json) — a sample of a real `results.json`.

Rules: [Controller design](controller-design.md).

Imagine that the prize task has just concluded.

---

## Playback & scoring (same every studio task)

Steps 1–5 follow the fixture until Alex has entered this task's scores.

---

### Playback — step 1

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Ep 01 · Task 01 · Step 1 of 5 · TV: idle                    ● Connected │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Now it's time for a slimy task. (Throw frog).                           │
│                                                                          │
│  Next clip: intro                                                        │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  [Back]  [Play specific ▼]  [Play next clip]                             │
└──────────────────────────────────────────────────────────────────────────┘
```

---

### Playback — step 2

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Ep 01 · Task 01 · Step 2 of 5 · TV: intro                  ● Connected  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Each contestant has one frog and one throw. The frog must land intact.  │
│  Measurements taken from the line to the frog's nose.                    │
│                                                                          │
│  Next clip: taylor-max                                                   │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  [Back]  [Cancel playing]  [Play specific ▼]  [Play next clip]           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

### Playback — step 3

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Ep 01 · Task 01 · Step 3 of 5 · TV: taylor-max             ● Connected  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Taylor threw it 31 m — the length of half a frog on a 30.95 m stick.    │
│  Max threw it 12 m into a bush and argued it counted. 12m is the length  │
│  of a really long cat.                                                   │
│  Next clip: peter-harry                                                  │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  [Back]  [Cancel playing]  [Play specific ▼]  [Play next clip]           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

### Playback — step 4

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Ep 01 · Task 01 · Step 4 of 5 · TV: peter-harry            ● Connected  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Peter threw it 28 m with excellent form. Harry's frog escaped and was   │
│  not recovered.                                                          │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  [Back]  [Cancel playing]  [Play specific ▼]  [Score]                    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

### Scoring — step 5

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Ep 01 · Task 01 · Step 5 of 5 · TV: idle                    ● Connected │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Overall: Peter 1st (28 m), Taylor 2nd furthest (31 m), but disqualified,│
│  then Max (12m), Harry's escaped, Charlie absent.                        │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  Taylor  [0][1][■2■][3][4][5]   Max     [0][1][2][■3■][4][5]             │
│  Charlie [■0■][1][2][3][4][5]   Peter   [0][1][2][3][4][■5■]             │
│  Harry   [0][■1■][2][3][4][5]                                            │
├──────────────────────────────────────────────────────────────────────────┤
│  [Back]  [Play specific ▼]  [Scoreboard]                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

**Branch point** — **Scoreboard** always goes to prep. From there, how many scoreboards go on the TV before the next segment:

| TV scoreboards | Path | Buttons |
| -------------- | ---- | ------- |
| **0** | Skip display | Prep → **Next task** |
| **1** | Episode only | Prep → **Display episode scoreboard** → post-display → **Next task** |
| **2** | Episode + series | As 1, then **Series scoreboard** on post-display → **Next task** |

*(If this were the last studio task in the episode, **Next task** would read **Live task** instead — see [Controller design §5](controller-design.md#5-live-task).)*

---

## 0 scoreboards — skip display

### Prep

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Ep 01 · Task 01 · Scoreboard prep · TV: idle                ● Connected │
├──────────────────────────────────────────────────────────────────────────┤
│  Episode scores                                                          │
│  1. Peter      8                                                         │
│  2. Taylor     6                                                         │
│  3. Charlie    5                                                         │
│  4. Max        5                                                         │
│  5. Harry      2                                                         │
├──────────────────────────────────────────────────────────────────────────┤
│  [Back]  [Next task]              [Display episode scoreboard]           │
└──────────────────────────────────────────────────────────────────────────┘
```

→ [Next task — task 02 step 1](#next-task--task-02-step-1)

---

## 1 scoreboard — episode on TV

### Prep

Same as above; Alex taps **Display episode scoreboard**.

### Post-display

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Ep 01 · Task 01 · On screen · TV: ep scorebrd              ● Connected  │
├──────────────────────────────────────────────────────────────────────────┤
│  Series standings                                                        │
│  1. Peter      8        2. Taylor    6        3. Charlie   5             │
│  4. Max        5        5. Harry     2                                   │
├──────────────────────────────────────────────────────────────────────────┤
│  [Series scoreboard]                        [Next task]                  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Next task** → task 02. **Series scoreboard** → continue below.

*(ep01 is the season opener, so with no earlier episodes the series standings equal ep01's episode totals so far. In a later episode the series numbers would be higher. The tie at 5 — Charlie and Max — is broken alphabetically, so Charlie ranks above Max.)*

---

## 2 scoreboards — episode + series on TV

From post-display, Alex taps **Series scoreboard**. Same page; TV switches to the series animation.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Ep 01 · Task 01 · On screen · TV: series scorebrd          ● Connected  │
├──────────────────────────────────────────────────────────────────────────┤
│  Series standings                                                        │
│  1. Peter      8        2. Taylor    6        3. Charlie   5             │
│  4. Max        5        5. Harry     2                                   │
├──────────────────────────────────────────────────────────────────────────┤
│  [Series scoreboard]                        [Next task]                  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Next task** → task 02.

---

## Next task — task 02 step 1

All paths end here. TV cleared; **task02** opens.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Ep 01 · Task 02 · Step 1 of 7 · TV: idle                    ● Connected │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Make the best portrait of the Taskmaster using only food.               │
│                                                                          │
│  Next clip: intro                                                        │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  [Back]  [Play specific ▼]  [Play next clip]                             │
└──────────────────────────────────────────────────────────────────────────┘
```
