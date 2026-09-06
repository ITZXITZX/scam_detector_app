# Pattern Engine & Profile — Design

Proposal for Workflow A's checks and Workflow B's learning. Nothing here is
implemented yet. Supersedes the five-check sketch; see "What changed from the
sketch" at the end.

## The constraint everything follows from

> **The AI doesn't decide the verdict.** The deterministic checks decide. The AI
> explains, advises, and can raise a concern — but it can't overrule a domain
> check.
> — Rule 2

Today the opposite is true: `riskScore` is whatever Claude returns, clamped to
0–100. Not reproducible, not auditable, not tunable.

The original sketch would not have fixed that. Four of its five checks were
"does this behaviour match a known scam pattern?" — fuzzy matching, i.e. more
LLM judgement. Only the link check was deterministic.

## Three layers

```
  frames ──► LAYER 1  Signal extraction        (LLM, fixed taxonomy)
                 │     labels, never judges
                 ▼
             LAYER 2  Deterministic checks     (pure Python)
                 │     exact, free, explainable
                 ▼
             LAYER 3  Scoring & verdict        (pure Python, rule table)
                 │     reproducible and tunable
                 ▼
             LAYER 4  Advice                   (LLM)
                       explains a verdict it did not decide
```

The LLM appears twice, and in neither place does it decide anything. Layer 1 is
classification, which models are good at. Layer 4 is writing, which models are
good at. The verdict sits between them, in Python.

---

## Layer 1 — Signal taxonomy

Claude returns exactly these fields, all closed enums. Anything outside the enum
is a bug, not a new category.

| Field | Values |
|---|---|
| `lureType` | `authority`, `investment`, `romance`, `parcel`, `job`, `lottery`, `tech_support`, `ecommerce`, `impersonation_known_person`, `other`, `none` |
| `pressureTactics[]` | `urgency`, `secrecy`, `threat`, `isolation`, `flattery`, `reciprocity`, `authority_claim` |
| `requestedAction` | `transfer_money`, `share_credentials`, `share_otp`, `share_id_document`, `install_app`, `click_link`, `buy_giftcard`, `meet_in_person`, `none` |
| `claimedIdentity` | `police`, `bank`, `government`, `courier`, `platform_support`, `known_person`, `stranger`, `none` |
| `channel` | `whatsapp`, `telegram`, `sms`, `wechat`, `facebook`, `instagram`, `unknown` |
| `engagementDepth` | `no_reply`, `replied`, `shared_personal_info`, `shared_credentials`, `initiated_payment` |
| `urls[]` | every URL seen, rejoined across line wraps |

Two properties matter:

- **Closed enums** make Layer 3 a lookup rather than an interpretation.
- **This is also the profile vocabulary.** Workflow B's "what we record" table is
  the same list, so learning comes almost free (see Layer 5).

`engagementDepth` is read from the user's own messages — did they reply, hand
over details, start a transfer. It is the "how deep they got" signal.

---

## Layer 2 — Deterministic checks

### Buildable now

| Id | Check | Fires when |
|---|---|---|
| `C1` | **Domain not official** | A URL's registrable domain is absent from the official-domain allowlist |
| `C2` | **Authority claim, unofficial link** | `claimedIdentity ∈ {police, government, bank}` **and** a URL is not on that org's allowlist |
| `C3` | **Lookalike domain** | Registrable domain is confusable with an allowlisted one — edit distance ≤ 2, or contains an allowlisted brand as a non-domain substring (`dbs-secure.co`, `mas-verify.sg-alert.test`) |
| `C4` | **Credential or OTP request** | `requestedAction ∈ {share_credentials, share_otp}` |
| `C5` | **Payment under authority claim** | `requestedAction == transfer_money` **and** `claimedIdentity ∈ {police, government, bank}` |
| `C6` | **Known-bad domain** | Domain appears in the local blocklist |
| `C7` | **Isolation instruction** | `isolation` or `secrecy` in `pressureTactics` |

C4, C5 and C7 read Layer 1's structured output rather than raw text. They are
still deterministic — the same signals always produce the same result.

**C3 is the check that already proved itself.** In testing, the link wrapped
across two lines and read as `mas-verify.sg`, which looks like a legitimate
`.sg` domain. The real host was `sg-alert.test`. A person skims and misses that;
a string comparison never does.

### Not buildable yet — needs a data source

| Check | Blocker |
|---|---|
| ScamShield behaviour match | **No public API.** ScamShield is a consumer app plus the 1799 helpline. Users check numbers, sites and messages in-app; there is no developer endpoint. Do not reverse-engineer the app's private endpoints — fragile, against terms, and the worst possible place to do it |
| ScamShield site/app match | Same |
| Recent scam news match | No RSS or API found for `scamalert.sg`, SPF advisories or ScamShield. See Layer 6 |

The original sketch listed "recent scam news" twice; treated here as one item.

### The allowlist

A checked-in file, not a live lookup. Starting set:

```
*.gov.sg
dbs.com.sg  posb.com.sg  ocbc.com  uob.com.sg  scb.com.sg
singpass.gov.sg  cpf.gov.sg  iras.gov.sg
singpost.com  ninjavan.co
```

Small, boring, and the highest-value component in the system. Being a checked-in
file makes every verdict reproducible at a given commit.

---

## Layer 3 — Scoring and verdict

```
score = Σ points(fired checks) + Σ points(signals)
```

| Source | Points |
|---|---|
| `C2` authority claim + unofficial link | **hard trigger** |
| `C3` lookalike domain | **hard trigger** |
| `C6` known-bad domain | **hard trigger** |
| `C4` credential/OTP request | 40 |
| `C5` payment under authority claim | 35 |
| `C7` isolation or secrecy | 20 |
| `C1` domain not official | 15 |
| each pressure tactic | 5 (max 20) |
| `lureType != none` | 10 |

```
verdict = SCAM             if any hard trigger fires, or score ≥ 60
          COULDN'T CONFIRM otherwise
```

**There is no "safe" outcome**, per Rule 1. `COULDN'T CONFIRM` carries the 1799
referral.

Everything here is arbitrary *but visible*. You can tune it, unit-test it,
explain it to a user, and diff it in review — none of which is true of a number
a model picked. The numbers matter less than the fact that they exist somewhere
you can point at.

The response should carry the fired checks, so the UI can say *why*.

---

## Layer 4 — Advice

The LLM receives the verdict, the fired checks, and the user's profile, and
writes plain-language advice. It **cannot change the verdict**.

Fixes two things about today's behaviour:

- `warnings` has drifted into ad-hoc advice with no house style and no
  consistent helpline. Advice becomes its own field, and 1799 is fixed by
  template rather than left to the model.
- Advice can reference the profile: *"this is the same pattern as the message
  you checked in April"* — Workflow C's phrasing, available in Workflow A.

Prompt-injection rule stays: screen text is data, never instructions.

---

## Layer 5 — Profile (Workflow B)

```
UserProfile
  userId
  encounters[]        { at, lureType, tactics[], channel, depth, verdict }
  vulnerability{}     lureType -> float     (derived)
  tacticSensitivity{} tactic   -> float     (derived)
  channels{}          channel  -> count
```

Derived scores, not stored ones — recomputed from `encounters` so the weights
can change without migrating data.

### The two rules, as one formula

```
vulnerability[lure] = Σ over encounters with that lure:
                          depth_weight(e) × 0.5 ^ (age_days(e) / HALF_LIFE)
```

| Depth | Weight | |
|---|---|---|
| `no_reply` | 1 | checked before engaging |
| `replied` | 2 | |
| `shared_personal_info` | 4 | |
| `shared_credentials` | 6 | |
| `initiated_payment` | 8 | nearly lost money |

`HALF_LIFE = 90 days`. A vulnerability halves every quarter unless it recurs —
"recent matters more", as arithmetic rather than a policy someone has to
remember.

`tacticSensitivity` uses the same formula over `pressureTactics`.

This yields exactly the sentence in the workflow doc: *"highly vulnerable to
authority scams, moderately to fear-based, not at all to parcel scams. Usually
targeted on WhatsApp."*

---

## Layer 6 — Campaigns and news ingestion (Workflow C)

**Because campaigns are described in the same taxonomy as profiles, matching is
arithmetic, not judgement.**

```
Campaign
  id, description
  signature { lureType, tactics[], channel }
  severity
  activeFrom, activeUntil
```

```
match_score(user, campaign) = vulnerability[campaign.lureType]
                            + Σ tacticSensitivity[t] for t in campaign.tactics
                            + channel_bonus
warn if match_score ≥ threshold and weekly quota allows
```

No model is consulted to decide who gets warned. That keeps Rule 2 intact at the
moment it matters most — the pre-emptive warning is the product's whole pitch,
and it must be explainable.

### Ingesting news — answering "can this be automated later?"

Yes, in stages. No public feed exists today for `scamalert.sg`, SPF advisories
or ScamShield, so:

**Stage 1 — manual (start here).** A human writes campaigns straight into the
store as a taxonomy signature. Sounds unambitious, but: it is the demo path
(beat 3 is "a new campaign is added, seconds later her phone buzzes"), it needs
no scraping, and it forces the taxonomy to prove it can express real campaigns.

**Stage 2 — assisted.** A scheduled job pulls the SPF advisories and ScamAlert
pages, and an LLM converts each item's prose into a proposed campaign signature.
**A human approves before it goes live.** The model translates prose into the
taxonomy; it does not decide who gets warned. Rule 2 survives, because a
campaign is data, not a verdict.

**Stage 3 — automatic.** Only once stage 2 has produced enough
approved-vs-rejected pairs to know the translation is trustworthy, and with a
kill switch.

The thing that makes any of this possible is the shared taxonomy. A news article
becomes `{lureType: authority, tactics: [urgency, secrecy], channel: phone}` —
and that object is directly comparable to every user profile.

---

## API shape

`POST /recordings/{id}/analyze` gains:

```jsonc
{
  "signals": { "lureType": "authority", "pressureTactics": ["urgency", "secrecy", "isolation"],
               "requestedAction": "transfer_money", "claimedIdentity": "police",
               "channel": "telegram", "engagementDepth": "replied",
               "urls": ["https://mas-verify.sg-alert.test/case/114872"] },
  "checks":  [ { "id": "C3", "fired": true,
                 "detail": "sg-alert.test resembles an official domain but is not one" },
               { "id": "C5", "fired": true,
                 "detail": "asked for a transfer while claiming to be the police" } ],
  "verdict": { "outcome": "SCAM", "score": 100, "hardTriggered": ["C3"] },
  "advice":  { "headline": "This is a scam. Do not transfer any money.",
               "whatToDo": ["Do not reply", "Do not transfer", "Call 1799"] }
}
```

`analysis.riskLevel` / `riskScore` are replaced by `verdict`. The UI gains a
"why" list from `checks` — currently it can only show a number and a sentence.

---

## Build order

1. **Allowlist + C1/C2/C3** — pure Python, unit-testable with no API key, no UI
2. **Layer 1 extraction** — replace the free-form verdict with the taxonomy
3. **Layer 3 scoring** — the verdict becomes reproducible
4. **Layer 4 advice** — 1799 by template
5. **Profile** — feed it results, watch the scores move
6. **Campaigns + matching + push** — *this is the demo*

Steps 1–3 remove the "the model picked 95" problem. Everything after depends on
the taxonomy existing, which is why it is worth getting right first.

---

## Open questions

1. **Depth from one screenshot?** `engagementDepth` assumes we can see the
   user's own replies. A forwarded message alone shows nothing. Default to
   `no_reply`, or leave it unknown and exclude from scoring?
2. **Who is "the user" without accounts?** The profile needs a stable id.
   Device-local, or does this force sign-in?
3. **Are the weights right?** They are guesses. The point is that they are
   visible guesses, but they should be checked against real cases before the
   demo.
4. **Where does the blocklist come from?** C6 assumes one exists. Manual, or a
   public feed with acceptable terms?

---

## What changed from the sketch

| Sketch | Here | Why |
|---|---|---|
| 5 checks, 4 fuzzy | 7 deterministic checks + LLM classification | Fuzzy matching is LLM judgement, which Rule 2 forbids |
| ScamShield lookup ×2 | dropped | No public API |
| "Recent scam news" ×2 | one item, deferred to campaigns | Duplicated in the original |
| Verdict from checks | unchanged | Already correct |
