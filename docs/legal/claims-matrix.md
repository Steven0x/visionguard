# Claims matrix

> **DRAFT: needs IP attorney review and sign-off before any notice is sent.** This is a research-based starting point, not legal advice. Status: `unapproved`. The `claims-checker` agent treats every row as provisional until this banner is removed.

Every case must map to exactly one primary claim type below. The claim decides the channel, the required support, and the notice contents.

## Claim types

| Claim type | Use when | Allowed channels | Required rights record | Don't use for |
| --- | --- | --- | --- | --- |
| `copyright` | An original photo, video, illustration or product photo the subject owns, or holds an exclusive license to, is copied or closely derived | DMCA notice to platform, host or CDN; Google copyright removal; platform copyright forms | Proof of ownership or exclusive license (originals with metadata, agency or photographer agreement, registration if any) + agent authorization | Logos or brand names alone; a face in a photo the subject didn't take or own |
| `trademark` | A registered or clearly established mark is used in a way likely to confuse (counterfeits, lookalike listings, fake stores) | Platform trademark/IP forms (Amazon Brand Registry, Meta IP form, eBay VeRO, etc.); demand letter | Trademark registration (number, owner, classes) + agent authorization | **Never via DMCA.** Not for a single color or a font on its own |
| `likeness` | A person's name, face or voice is used commercially without consent (fake ads, endorsements, product use) | Platform privacy/impersonation/IP forms; demand letter | Subject's consent and authorization for VisionGuard to act; proof of identity | Non-commercial commentary, news, parody |
| `ncii` (Take It Down Act) | Intimate imagery of the subject, real or AI-generated, shared without consent | The platform's Take It Down Act removal process; platform NCII forms | Subject's identity verification + authorization. **Open question:** can an authorized agent file on the subject's behalf on each platform? | Anything not intimate imagery |
| `impersonation` | An account poses as the subject or brand | Platform impersonation reports | Proof of identity (subject) or of brand ownership | Fan and parody accounts that are clearly labeled |

## Required notice elements

### `copyright` (DMCA §512(c)(3))

1. Physical or electronic signature of the owner or an authorized agent
2. Identification of the copyrighted work
3. Identification of the infringing material and its location (URLs)
4. Contact information for the complaining party
5. A good-faith belief that the use isn't authorized by the owner, its agent, or the law
6. A statement, under penalty of perjury, that the notice is accurate and the sender is authorized to act for the owner

Before filing, the reviewer must consider fair use (*Lenz v. Universal*).

### `trademark` / `likeness` / `impersonation`

Follow each platform's form fields. Always include: identity of the rights holder, the registration number (trademark), infringing URLs, a description of the confusion or misuse, the agent's authorization, and a good-faith and accuracy statement.

### `ncii`

Follow the platform's Take It Down Act process: identification of the content, a statement that the depicted person didn't consent, information to contact the requester, and a signature. Platforms must remove it within 48 hours of a valid request.

## Escalation and recovery

| Step | When | Requirements |
| --- | --- | --- |
| Demand letter | Commercial misuse with an identifiable business | Approved template; fair, documented fee basis; no demands against non-commercial individuals |
| Copyright Claims Board | Copyright claims up to $30,000 per case ($15,000 per work) | A filed registration application; respondent can opt out |
| Partner attorney | High-value cases, registered works | Referral agreement. **Open question:** fee-splitting rules with non-lawyers by state |

## Open questions for counsel

- [ ] Agent authorization language for each claim type (a single power-of-attorney style document, or separate ones?)
- [ ] Can VisionGuard, as an authorized agent, file Take It Down Act requests on each major platform?
- [ ] State right-of-publicity coverage for the launch states (NY, CA, FL)
- [ ] Recovery fee structure and fee-splitting compliance
- [ ] Retention periods for evidence and for intimate-image hashes
