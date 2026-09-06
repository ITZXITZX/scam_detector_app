# How Sentry Decides

Architecture reference for the pattern engine, the ScamShield knowledge base,
the user profile and the advice layer.

*Backend as of 6 September 2026. 85 tests, none requiring an API key.*

---

## The idea in one paragraph

A language model reads the screenshots and writes the advice. It does not decide
whether something is a scam. Everything between those two points is Python you
can read, test and argue with.

An earlier version asked the model for a risk score directly. The same
conversation could not be relied on to produce the same number twice, the number
could not be explained to the person it was about, and there was no dial to turn
when it was wrong. Moving the decision into Python also moved it into `pytest`.

Throughout this document:

- **[PY]** marks a step decided in Python — deterministic and reproducible.
- **[AI]** marks a step handled by Claude Haiku — labelling and phrasing only.

---

## 1. The pipeline

One tap of *Analyse conversation* runs seven steps.

| # | Step | Decided by | In | Out |
|---|------|-----------|----|-----|
| 1 | Read the frames | **[AI]** | 8 images (~8,000 tokens) | transcript + 9 labelled signals |
| 2 | Run the checks | **[PY]** | signals | 12 CheckResults |
| 3 | Score and decide | **[PY]** | CheckResults | `SCAM` \| `COULDNT_CONFIRM`, 0–100 |
| 4 | Look up the guidance | **[PY]** | lureType | 1 of 12 YAML entries |
| 5 | Read the profile | **[PY]** | userId | counts only, never content |
| 6 | Write the advice | **[AI]** | verdict + guidance + history | headline + step indexes |
| 7 | Render and record | **[PY]** | step indexes | verbatim text + one SQLite row |

**Step 1 does two jobs in one call** — transcription and labelling — because it
is the only call that sees pixels. `channel` is read off the app's chrome, not
its words. A separate call would mean re-sending either the screenshots or the
whole transcript just to categorise them.

**Step 5 runs before step 7** deliberately, so "the third time" counts the times
before this one.

---

## 2. Signals

What the model is allowed to say about a conversation. Every field is a closed
enum, so scoring is a lookup rather than an interpretation: a value outside the
list is a bug, not a new category.

| Field | Values | Notes |
|---|---|---|
| `lureType` | authority, investment, job, ecommerce, phishing, fake_friend, loan, tech_support, insurance, romance, sexual_service, other, none | ScamShield's own categories, so a campaign written up as a "loan scam" has somewhere to land. Cryptocurrency is deliberately absent — ScamShield's own page says crypto scams fall into government-impersonation, investment and job scams, so it is a payment rail, not a lure. |
| `pressureTactics` | urgency, secrecy, threat, isolation, flattery, reciprocity, authority_claim | A list. 5 points each, capped at 20. |
| `requestedActions` | transfer_money, transfer_crypto, share_credentials, share_otp, share_singpass, share_id_document, install_app, install_remote_access, click_link, buy_giftcard, pay_upfront_fee, meet_in_person | A list, not one value. Scams ask in sequence — open this, confirm your NRIC, then transfer — and a single label hid the rest from every check reading it. |
| `claimedIdentity` | police, bank, government, courier, platform_support, known_person, stranger, none | Who they *say* they are. Never verified, never treated as true. |
| `channel` | whatsapp, telegram, sms, wechat, facebook, instagram, unknown | Read from the app's interface. Returns `unknown` more often than not — the weakest signal in the set. |
| `engagementDepth` | no_reply, replied, shared_personal_info, shared_credentials, initiated_payment | How far the user went, judged only from their own messages. |
| `unsolicitedContact` | true / false | Whether the approach was invited. Two hard triggers depend on it. |
| `urls` | list of strings | Rejoined across line wraps. A wrapped link read as `mas-verify.sg` and hid that its owner was `sg-alert.test`. |
| `modelSuspicion` | none, moderate, strong (+ a required observation) | The model's structural read, against a written rubric. A label rather than a number, so it can be checked for stability. |

---

## 3. The checks

Twelve pure functions. No network, no clock, no model. Each reads **labels,
never message text**, which is what stops a scam from arguing with the check
that catches it.

| ID | Fires when | Points | Where the rule comes from |
|---|---|---|---|
| C1 | A link whose owner is not on the allowlist | 15 | Weak by design — most of the web is not on it |
| C2 | Claims police, bank or government, links to a domain they do not own | 100 **HARD** | A real agency does not send you off its own domain |
| C3 | Brand name used by a host that does not own it, or a near-miss spelling | 45 | Scored, not decisive — token matching can misfire |
| C4 | Asks for a password, OTP or Singpass credentials | 40 | ScamShield: "SPF officers will NEVER request your banking, SingPass or CPF information" |
| C5 | Asks for a transfer while claiming authority | 35 | The shape of most impersonation scams that end in a loss |
| C7 | Pressures the user toward secrecy or isolation | 20 | Scams rarely survive contact with a third party |
| C11 | The model's own structural read | 0 / 20 / 50 | Capped below the threshold on purpose |
| C12 | A link sent by SMS while claiming to be a bank | 50 | ScamShield: "Banks will never send you any clickable links via SMS" |
| C13 | A loan offered to someone who did not ask for one | 100 **HARD** | ScamShield: "Any unsolicited loan offer is a scam" |
| C14 | Remote-access software requested by an unsolicited caller | 100 **HARD** | ScamShield: it "gives them full control of your device" |
| C15 | A job that wants payment before it starts | 45 | ScamShield lists it under "likely a scam if the job requires you to…" |
| C16 | Payment demanded in gift cards or cryptocurrency | 40 | ScamShield: "cryptocurrency transfers are non-reversible" |

### Missing numbers

C6, C8, C9 and C10 do not exist.

- **C6** was a known-bad domain list, deferred for want of a source worth
  depending on.
- **C8–C10** were structural checks for unsolicited offers and contradicted
  identities. They were dropped because their weights had been fitted to a
  single screenshot, which is overfitting with a sample size of two.

The gaps are left in place so the numbering keeps matching the history.

### Scoring

```python
score = sum(points of fired checks)
      + min(5 × pressure tactics, 20)
      + 10 if lureType != none
      + {none: 0, moderate: 20, strong: 50}[modelSuspicion]

verdict = SCAM             if any hard trigger or score >= 60
          COULDNT_CONFIRM  otherwise
```

There is no "safe" outcome. `COULDNT_CONFIRM` carries the 1799 referral — a
false reassurance is the one mistake that costs someone their savings.

### Why the model's suspicion is capped at 50

The threshold is 60. The model can push a conversation over the line alongside
other evidence and can never supply all of it, so a misread of a legitimate
conversation cannot produce a scam verdict unaided.

It is also **escalate-only**: a fired domain check stands regardless of what the
model thinks.

---

## 4. The ScamShield data

`backend/knowledge/scamshield.yaml` — 12 entries, 12.5 KB, one per lure type.
A checked-in file, not a database: a verdict has to be reproducible at a given
commit, and a reviewer has to be able to see what the system trusts.

```yaml
loan:
  source:      https://www.scamshield.gov.sg/.../loan-scams/
  retrieved:   2026-09-06
  keyTakeaway: Never pay upfront fees to receive a loan.
  neverHappens:                  # → deterministic checks
    - Any unsolicited loan offer is a scam
    - Licensed moneylenders are prohibited from advertising
  redFlags:
    - A loan advertised on social media or sent unprompted
  whatToDo:                      # → shown to the user, verbatim
    - Check the Registry of Moneylenders for licensed lenders
    - Do not transfer any money to receive a loan
    - Call 1799 if you are unsure
```

### One file, two jobs

| Field | Used in | How |
|---|---|---|
| `neverHappens` | Step 2 — checks | Categorical statements become checks. C13 exists because "any unsolicited loan offer is a scam" is a published rule, not a judgement anyone here made. Where the source is categorical, the check decides the verdict alone. |
| `whatToDo` | Steps 4 & 6 — advice | Numbered and handed to the model, which returns only the indexes that apply. The user reads ScamShield's exact wording. |
| `source`, `retrieved` | Provenance | A claim like "banks never send links by SMS" is only as good as who said it and when. |

### Why there is no retrieval step

Twelve documents and a key the pipeline already produced. Embeddings and
similarity search would add a dependency, a failure mode and a source of
non-determinism to solve a problem `dict[lure]` solves exactly. Retrieval earns
its place when you cannot know in advance which document you need — here you
always can.

---

## 5. The profile

One SQLite table of encounters. Everything the app shows is derived on read, so
the weights can change without a migration.

| Column | Holds |
|---|---|
| `user_id` | A random id the app generates on first launch. No account, no email. |
| `at` | When it was checked. |
| `lure_type`, `tactics`, `channel`, `depth` | The labels from step 1. |
| `outcome`, `score` | The verdict from step 3. |
| `recording_id` | Which upload it came from. The frames themselves are deleted after 15 minutes. |

### What is deliberately not stored

No message text. No URLs. Nothing identifying the other party. **The schema has
no column that could hold any of it, and a test asserts as much.**

Workflow D promises a family member sees the *shape* of someone's risk and never
the content. That promise is easiest to keep if the content was never written
down.

### Derived on read

```
vulnerability      {lure: count}      # how many times each kind reached them
tacticSensitivity  {tactic: count}
channels           {channel: count}
lureCounts         {lure: count}      # drives "3rd authority scam you've checked"
topLure            str | None
usualChannel       str | None         # excludes "unknown" — an unknown is not a habit
```

These are whole numbers on purpose. An earlier version weighted each encounter
by depth and faded it exponentially with age — accurate, and unreadable: the
screen said `authority 8.14`, which invites a question with no good answer.

Every encounter still stores its timestamp and depth, so weighting can come back
whenever there is somewhere to put it that is not the user's face.

### Stored labels outliving the taxonomy

Enum values are written to disk, so removing one strands every row that used it.
Aligning the lure taxonomy to ScamShield's categories removed `parcel`, and a
single stranded row returned a 500 for the whole profile.

Known renames now map on read (`parcel → phishing`, `lottery → other`,
`impersonation_known_person → fake_friend`), and anything unrecognised falls
back rather than raising. Losing a label is recoverable; losing the history is
not.

---

## 6. The advice layer

The last step, and the one that most easily drifts. Its design is a single idea:
**the model selects, it does not write.**

```
# what the model receives
verdict:         SCAM
reasons:         ["Claims to be police but links to sg-alert.test…", …]
history:         {timesThisKindSeenBefore: 2, totalConversationsChecked: 9}
officialSteps:   0. Do not transfer any money, whatever the caller says
                 1. Hang up and call the ScamShield Helpline on 1799 to check
                 2. Tell someone you trust before you act
                 3. Call your bank immediately and make a police report…

# what it returns
adviceHeadline:    "Do not click the link or enter any details; hang up
                    immediately and call 1799."
adviceStepIndexes: [0, 1, 2]

# what the user sees — rendered by Python, word for word
1. Do not transfer any money, whatever the caller says
2. Hang up and call the ScamShield Helpline on 1799 to check
3. Tell someone you trust before you act
```

When the model wrote advice freely, the helpline changed between runs: one run
cited a police website, another said something else, and neither was checked
against what the authorities publish. Inventing an agency is now **structurally
impossible** rather than discouraged — the model cannot write a step, only
choose one, and an out-of-range index is dropped rather than trusted.

Same shape as the suspicion label in step 1: constrain the model to a choice,
keep the content deterministic.

### What the user reads

The card leads with the verdict, then the headline, then the numbered steps. The
reasons sit behind *Why we flagged this*, collapsed.

Someone deciding whether to hang up needs the instruction, not the evidence for
it — an earlier version showed eight bullets mixing both, which is how a warning
stops being read.

There is no score on the card. It is deterministic now, but its weights are
still judgement calls, and "55" beside a threshold of 60 implies a precision
that is not there.

---

## 7. Known gaps

Written down because they are easier to argue with here than to rediscover
later.

**Nothing has been tested against a legitimate conversation.** Every fixture is
a scam. Thresholds are tuned entirely on true positives with no measurement of
false positives — and an app that calls your mother's actual bank a scam gets
uninstalled, after which it misses every real one.

**Two hard triggers rest on an unmeasured signal.** C13 and C14 both depend on
`unsolicitedContact`, which the model has never been asked to label on a real
conversation.

**The weights are guesses.** 40 for a credential request, a threshold of 60 —
chosen, not derived. The gain over the previous system is not accuracy; it is
that they are visible, testable and arguable in review.

**Channel detection barely works.** `channel` returns `unknown` on most real
conversations, which disables C12 and leaves the profile unable to say where
someone is usually reached.

**History reaches the advice but barely moves it.** On the same conversation, a
first-time user is told to call 1799 to verify and a user with three priors to
call 1799 to report. The reliable version of that message lives elsewhere and is
deterministic — the result screen computes "3rd authority scam you have checked"
in Dart.

---

## 8. Code that is currently unused

Kept deliberately, recorded so it is not mistaken for something load-bearing.

| Item | Status |
|---|---|
| `/recordings/{id}/ocr` + RapidOCR | Unreachable from the app. Costs 82 MB of dependencies (`onnxruntime`, `rapidocr`, `shapely`, `pyclipper`) and **no API charges** — it runs locally. Kept as a second opinion on extraction. |
| `summary`, `warnings` | Still generated on every analysis, displayed nowhere. The only genuinely wasteful item: ~100–150 output tokens per check. |
| `ScamAnalysis` shim (`riskLevel`, `riskScore`) | Dead apart from `flaggedMessageIndexes`, which belongs beside `checks`. |
| `OCRText`, `FrameOCRResult`, `OCRResult`, `runOcr` in Dart | Reference only each other. |
| `build_profile(now=…)` | Accepted and unused **on purpose** — documented, tested, and reintroducing age weighting should not change every call site. |
