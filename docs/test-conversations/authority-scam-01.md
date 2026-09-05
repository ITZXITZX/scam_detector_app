# Test Conversation 01 — Authority Impersonation (Singapore)

**Fictional test data.** Written to be acted out between two people on real phones
so the resulting screen recording can be fed through the Sentry pipeline.

Nobody is being deceived: both participants know this is a simulation.

**Links use the reserved `.test` TLD on purpose** so no one can accidentally visit
a live site. Swap them for a lookalike real TLD only if you are testing the
domain-age check, and never send that to anyone outside the test.

## Signals this conversation is designed to contain

| Signal | Where |
|---|---|
| Authority lure | claims to be Singapore Police Force / MAS |
| Urgency | "within 24 hours", "account will be frozen" |
| Secrecy | "do not discuss this with family members" |
| Domain mismatch | claims government, links to a non-`.gov.sg` address |
| Money movement | asks to transfer to a "safety account" |
| Escalating depth | victim replies repeatedly, nearly complies |

## Roles

- **A = "Officer Tan"** (the scammer) — use the phone that will NOT be recorded
- **B = the victim** — use the phone that WILL be recorded

Type these in order into any messaging app. Don't rush; let each message land.

---

A: Good afternoon. Am I speaking with the owner of this number?

B: yes who is this

A: This is Officer Tan from the Singapore Police Force, Commercial Affairs Department. My officer ID is SPF-88412. I am contacting you regarding Case Reference CAD/2026/114872.

B: what case

A: Your NRIC has been linked to a bank account used in a money laundering syndicate. Three accounts were opened in your name at different banks last month.

B: i didnt open any accounts

A: We understand. This is why we are contacting you before escalation. Many victims have had their identity misused without their knowledge.

B: ok so what do i do

A: First, I must inform you that this case is under active investigation. You are not permitted to discuss it with anyone, including family members, until verification is complete. Doing so may be treated as obstruction.

B: why cant i tell my family

A: Any party you inform becomes a person of interest in the investigation. We are protecting them as much as you.

B: ok

A: I will now transfer you to our verification portal. Please open this link and complete identity verification: https://mas-verify.sg-alert.test/case/114872

B: is this official

A: Yes. This is the Monetary Authority of Singapore secure verification system. You may verify my identity by checking the case reference on the portal.

B: ok im opening it

A: Do not use public wifi while accessing the portal. Confirm when you can see the case reference.

B: yes i see CAD/2026/114872

A: Good. Now please confirm your full name, NRIC number and date of birth so I can match your record.

B: do you need my nric

A: Yes. Without identity confirmation I cannot clear your name from the syndicate list.

B: ok sending

A: Thank you. I can now see three flagged accounts. To protect your remaining funds, MAS will hold them in a government safety account for the duration of the investigation.

B: hold my money?

A: The funds are returned in full within 5 working days once you are cleared. This is standard procedure under the Anti-Money Laundering Act.

B: how much

A: The full balance of your primary savings account. Please confirm the amount available.

B: about 18k

A: Noted. Please transfer SGD 18,000 to the safety account: 
Account: 471-88214-9 
Bank: OCBC 
Name: MAS ASSET PROTECTION

B: this feels weird

A: I understand your hesitation. This is a normal reaction. Please note the transfer must be completed within 24 hours or your accounts will be frozen and the case escalated to court.

B: cant i just go down to the police station

A: The Commercial Affairs Department does not handle walk-ins for active cases. Attending in person will delay your clearance and may result in arrest.

B: ok give me a moment

A: Please confirm once the transfer is done. Remember, do not discuss this with anyone.

---

## How to record

1. Both phones ready. Type the conversation in real time, or paste it in quickly
   and then scroll back to the top
2. On phone **B**, start a screen recording
3. **Scroll slowly** from the top of the conversation to the bottom — roughly
   20 to 30 seconds. Slow enough that each message is fully readable in at least
   one frame
4. Stop the recording, transfer the `.mp4` to the PC

The scroll speed matters more than the length: it determines how many frames
survive dedup, which is exactly what we are measuring.
