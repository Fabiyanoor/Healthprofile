# Problem and Scenarios (Week 1)

## 1. Problem

A small HealthTech clinic app needs people to keep a personal health profile and an admin to oversee profiles. Two kinds of people use it, and mixing them up is the main risk. Login must be separate, and each person must see only what they are allowed to see. All data is synthetic.

## 2. Who uses it

| Who | What they want | What must never happen |
|---|---|---|
| Standard user | Sign up, log in, keep their own profile and emergency contacts up to date | Seeing or editing another person's profile, or reaching admin pages |
| Admin | Search and review profiles, deactivate a profile | Being created through a public page, or being impersonated by editing the browser |
| Attacker | Steal a login, guess passwords, reach data they don't own | Succeeding at any of it |

## 3. Simplest architecture that meets this

- Django + DRF backend, PostgreSQL, Next.js frontend, one backend serving two login styles.
- Users: short-lived JWT in HttpOnly cookies. Admins: server-side session plus CSRF.
- Each endpoint declares exactly one login style, so the two can never be mixed.
- Not built in Week 1: ML, RAG, agents, audit events, Docker, email verification, password reset.

## 4. Scenarios and expected behavior

### Signup (S)
| ID | Scenario | Expected |
|---|---|---|
| S1 | Valid name, email, strong password | Account created, profile created automatically, no password in the response |
| S2 | Email already used, even with different capitals (`A@x.com` vs `a@x.com`) | Rejected with a clear error |
| S3 | Weak or common password, or too short | Rejected with the reason |
| S4 | Invalid email format, empty fields, very long text | Rejected with field-level errors |
| S5 | Email with spaces or capitals | Trimmed and stored in lowercase |
| S6 | Request tries to set `role=admin` | Ignored. Signup always creates a standard user |

### User login, token and logout (L)
| ID | Scenario | Expected |
|---|---|---|
| L1 | Correct credentials | HttpOnly cookies set (access 15 min, refresh 1 day) |
| L2 | Wrong password or unknown email | Same generic error for both, so attackers can't learn which emails exist |
| L3 | Access token expired | 401, and the refresh cookie gets a new access token |
| L4 | Refresh token expired or tampered | 401, user must log in again |
| L5 | Logout | Cookies cleared. Known limit: a copied token stays valid until it expires |
| L6 | Deactivated user tries to log in | Rejected |
| L7 | An admin account tries the user login | Rejected |

### Own profile (P)
| ID | Scenario | Expected |
|---|---|---|
| P1 | View own profile | Returns only their profile |
| P2 | Partial update (change one field) | Only that field changes, `updated_at` moves |
| P3 | Date of birth in the future | Rejected |
| P4 | Both date of birth and age range | Rejected |
| P5 | Contact preference "phone" with no phone | Rejected |
| P6 | Request tries to change read-only fields (`user`, `status`, `deactivated_at`, `created_at`) | Ignored or rejected |
| P7 | No login cookie | 401 |
| P8 | Another user's data | Impossible by design. The URL has no id, the profile comes from the logged-in user |
| P9 | Empty update body | No change, no crash |

### Emergency contacts (E)
| ID | Scenario | Expected |
|---|---|---|
| E1 | Add first contact | Becomes primary automatically |
| E2 | Add second and third contact | Allowed, not primary |
| E3 | Add a fourth | Rejected with a clear message |
| E4 | Mark another contact primary | The old primary is demoted |
| E5 | Delete the primary | The oldest remaining contact becomes primary |
| E6 | Invalid phone number | Rejected |
| E7 | Touch a contact that belongs to someone else | Not found, as if it doesn't exist |

### Profile picture (F)
| ID | Scenario | Expected |
|---|---|---|
| F1 | JPG or PNG up to 2 MB | Accepted |
| F2 | Wrong type (for example `.exe` or `.pdf`) | Rejected |
| F3 | Larger than 2 MB | Rejected |
| F4 | Same file name as someone else's picture | No overwrite |

### Admin (A)
| ID | Scenario | Expected |
|---|---|---|
| A1 | Public admin signup | No such route exists |
| A2 | Admin created | Only through the `create_admin` command |
| A3 | Admin logs in | Server session cookie, expires after 30 minutes |
| A4 | Admin changes data without the CSRF token | Rejected |
| A5 | Admin logs out | Session deleted on the server |
| A6 | List profiles with search, status filter and pagination | Newest first, uses the composite index |
| A7 | View one profile | Full details, no password hash anywhere |
| A8 | Deactivate a profile | `status` and `deactivated_at` set, and the user can no longer log in |
| A9 | Standard user calls an admin route | Rejected |

### Role separation (R)
| ID | Scenario | Expected |
|---|---|---|
| R1 | User JWT cookie sent to an admin route | Rejected |
| R2 | Admin session cookie sent to a user route | Rejected |
| R3 | Browser state edited to say `role: admin` | No effect, the server checks the role itself |
| R4 | Token with a changed payload | Signature check fails, rejected |

### Data safety (D)
| ID | Scenario | Expected |
|---|---|---|
| D1 | SQL or script text in a field | Stored safely as text, never executed |
| D2 | Responses | Never contain password hashes, tokens or secrets |
| D3 | Seed data | At least 5 synthetic users and 1 admin, no real people |

## 5. How this document is used
- Each ID becomes at least one automated test.
- Each prompt names the IDs it must satisfy, so AI output can be checked against them.
- Anything AI gets wrong against an ID is a candidate for the "one AI bug" write-up.