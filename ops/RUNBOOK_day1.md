# Day-1 runbook: first client audit and takedowns

**Goal for tomorrow:** for the agency's 3–5 highest-priority talent, find what's out there, capture evidence, and file the first batch of takedowns through official channels. Then send the agency a short report. Don't try to cover the whole roster on day 1: a thorough job on a few people beats a shallow pass on everyone.

**Tools:** `VisionGuard_case_tracker.xlsx`, `capture/capture.py`, a browser, Google Lens, TinEye. Plan on 1.5–2 hours per talent.

---

## 0. Hard gate: don't file anything until these are in hand

- [ ] **Agency authorization** signed (`Authorization_to_Act.docx`) naming VisionGuard as authorized agent.
- [ ] **Talent authorization** signed by each person you'll file for (same form). The agency's signature alone may not be enough for likeness or intimate-image claims; get the talent's own signature.
- [ ] **Who owns each photo.** Models often don't own the copyright in their photos; the **photographer** does. You can only file a **copyright** claim for content the talent (or agency) owns or has an exclusive license to, or with the photographer's written authorization. Otherwise use **likeness**, **impersonation** or **NCII** routes. Self-shot creator content (OnlyFans, etc.) is usually owned by the creator.
- [ ] **Priorities:** the agency's list of the 3–5 people with the most urgent problems, plus any known links.

Record all of this on the **Talent** sheet of the tracker.

## 1. Intake (15 min per talent)

1. Add them to the Talent sheet: legal name, stage names, every handle, residence state.
2. Collect 10–20 reference photos: the most-shared shots, recent campaigns, profile photos, and for creators, previews of their paid content. Save to `reference/<Talent ID>/`.
3. Collect any links the agency or talent already knows about. These are the fastest wins.

## 2. Discovery (45–60 min per talent)

Log every hit worth a second look straight into the **Cases** sheet (status `Discovered`).

**Reverse image search** (5–10 best reference photos):

- [Google Lens](https://lens.google.com): upload the photo, open "Exact matches" first, then "Visual matches".
- [TinEye](https://tineye.com): best for exact and resized copies; sort by "Oldest" to find the original.
- Crop to just the face or the distinctive part and search again; cropped reposts often only match that way.

**Keyword searches** (Google; repeat for each stage name and handle):

- `"<stage name>" leaked` · `"<stage name>" onlyfans` · `"<name>" free` · `"<handle>" mega OR telegram`
- `site:t.me "<stage name>"` · `site:reddit.com "<stage name>"` · `site:x.com "<stage name>"`
- `"<name>" -site:<their real domains>` with image results

**Impersonation sweep:**

- Search each platform (Instagram, TikTok, X, Facebook, Telegram) for the name and small handle variations: extra underscore, `.official`, `_backup`, swapped letters.
- Check whether accounts use the talent's photos or ask followers for money or "exclusive" content.

**Fake ads:** search the [Meta Ad Library](https://www.facebook.com/ads/library/) for the talent's name.

## 3. Triage (fast, before capturing)

For each `Discovered` row, set:

- **Confirmed**: it's really them, used without permission. Pick the **Violation type**.
- **Dismissed**: not them, or licensed (check with the agency), or the talent's own account, or news, commentary or parody. Note the reason.

When unsure, ask the agency. Never file on a maybe.

## 4. Capture evidence (before filing, every time)

```bash
cd ops/capture
python capture.py capture --case VG-0007 --subject "T-003" --note "impersonation account" "https://instagram.com/fake_handle"
# many URLs for one case:
python capture.py capture --case VG-0012 --subject "T-001" --note "leak thread" --file urls_vg0012.txt
# pages needing a login (e.g. Instagram): opens a visible browser
python capture.py capture --case VG-0007 --subject "T-003" --headed "https://instagram.com/fake_handle"
```

- If it says **LOAD FAILED**, retry with `--headed`. If it still fails, take a full-page screenshot by hand, save it in the case folder, and note it in the tracker.
- If it says **NO TIMESTAMP**, the evidence is still saved. Re-capture later to get a timestamp.
- Mark **Evidence captured? = Yes** and paste the folder path into the tracker.
- **Intimate content:** capture the page (URL, title, account), but don't copy the images anywhere beyond the capture folder. Keep that folder private.

## 5. Choose the claim

| Situation | Claim | Route |
| --- | --- | --- |
| Intimate image, real or AI-made, without consent | `ncii` | Platform's intimate-image / Take It Down Act form; Google's explicit-image removal; [StopNCII.org](https://stopncii.org) for hash blocking on partner platforms |
| Account pretending to be the talent | `impersonation` | Platform impersonation form (needs the talent's ID) |
| Leaked paid content or reposted photos **the talent owns** | `copyright` | Platform copyright form or DMCA email to the host; Google copyright removal to delist |
| Photo the **photographer** owns | `copyright` only with the photographer's written authorization; otherwise `likeness` or `impersonation` | As above |
| Face or name used in an ad or to sell something | `likeness` | Platform IP/privacy form; demand letter later (not day 1) |
| Unsure | Don't file | Note the question for counsel |

**Never** use DMCA for trademark or likeness issues.

## 6. File through official channels

Use the platforms' own forms on day 1. They contain the required legal statements, which is safer than custom notices until an attorney has approved templates.

| Platform | Where to file |
| --- | --- |
| Instagram | [Copyright report form](https://help.instagram.com/contact/552695131608132) · impersonation: in-app "Report → Pretending to be someone" or the Instagram Help Center impersonation form |
| Facebook | Help Center → "Report intellectual property" / impersonation reporting |
| TikTok | [IP policy and reporting](https://www.tiktok.com/legal/page/global/copyright-policy/en) |
| X | help.x.com → Forms → Intellectual property / Impersonation |
| Google Search (delist) | Google copyright removal (Legal Help → Report content for legal reasons) · [Explicit or intimate image removal](https://support.google.com/websearch/answer/13650142) |
| Reddit, Telegram, tube and leak sites | The site's DMCA or abuse contact (usually in the footer or terms); if there's none, the hosting provider's abuse contact (look it up with a WHOIS or hosting-lookup tool) |

For each filing:

1. Fill in the form as the **authorized agent**, using the talent's details and VisionGuard's contact email.
2. Screenshot the confirmation page. Save it in the case's evidence folder.
3. Log it on the **Filing log** sheet: date, case, exact channel, claim, who approved it, ticket number.
4. On **Cases**, set Status = `Filed` and fill in the Filed date. The tracker sets a re-check date 3 days out and highlights overdue follow-ups.

## 7. Follow up

- Check each filed URL on its re-check date. Removed: set Outcome = Removed and the response date. Still up: re-file or appeal, and note it.
- Removed items reappear often. Re-run the keyword searches weekly.

## 8. Report to the agency (end of day 1, then weekly)

Keep it to one page per talent:

- **Found:** number of items, by type (leaks, impersonators, fake ads, reposts)
- **Filed:** number, and where
- **Removed so far:** number, with median time to removal (from the Summary sheet)
- **Highlights:** the 2–3 worst items and their status
- **Needs from you:** missing authorizations, photographer contacts, confirmations of licensed use

---

## What not to do on day 1

- Don't send demand letters or ask anyone for money yet.
- Don't file anything you haven't confirmed and captured.
- Don't store or share intimate images outside the private evidence folder.
- Don't run face search on anyone who hasn't signed the authorization.
