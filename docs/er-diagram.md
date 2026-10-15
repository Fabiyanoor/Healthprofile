# ER Diagram

```mermaid
erDiagram
    USER ||--o| HEALTH_PROFILE : "owns (at most one)"
    HEALTH_PROFILE ||--o{ EMERGENCY_CONTACT : "has many (max 3 by validation)"
    USER ||..o{ DJANGO_SESSION : "conceptual only, no foreign key"

    USER {
        bigint id PK
        string email UK "lowercase, max 254"
        string name "max 150"
        string password "hashed, never plain text"
        string role "user or admin, indexed"
        bool is_active "default true"
        datetime last_login "set by Django on login"
        datetime created_at "auto"
    }

    HEALTH_PROFILE {
        bigint id PK
        bigint user_id FK, UK "ON DELETE CASCADE"
        string full_name "max 150"
        date date_of_birth "optional, not in future"
        string age_range "optional, used only if no date_of_birth"
        string phone "optional, validated format"
        string contact_preference "email, phone or none"
        string profile_picture "optional, file path only"
        text wellness_goals "optional"
        text allergies "optional"
        text lifestyle_notes "optional"
        datetime consent_accepted_at "when data use was accepted"
        string status "active or deactivated"
        datetime deactivated_at "set when an admin deactivates"
        datetime created_at "auto"
        datetime updated_at "auto on every save"
    }

    EMERGENCY_CONTACT {
        bigint id PK
        bigint profile_id FK "ON DELETE CASCADE, indexed"
        string name "fictional, max 150"
        string relationship "for example sibling, friend"
        string phone "fictional, validated format"
        bool is_primary "at most one true per profile"
        datetime created_at "auto"
    }

    DJANGO_SESSION {
        string session_key PK
        text session_data "holds the admin user id"
        datetime expire_date "indexed"
    }
```

## Why each design choice

**Tables**
- **USER:** one table for both roles, with a `role` field. Simple, and permissions are checked server-side.
- **HEALTH_PROFILE:** separate from USER so login data and health data stay apart.
- **EMERGENCY_CONTACT:** a person can have several contacts, so they live in their own table instead of repeated columns.
- **DJANGO_SESSION:** framework-managed, used only for admin logins. User JWTs are stateless, so they are not stored in the database.

**Relationships**
- **USER to HEALTH_PROFILE (at most one):** the unique foreign key allows one profile per user. A profile is created automatically at signup for standard users. Admins have none.
- **HEALTH_PROFILE to EMERGENCY_CONTACT (many):** the database allows many. The limit of 3 is enforced by server-side validation and tested.
- **ON DELETE CASCADE:** deleting a user removes their profile, and deleting a profile removes its contacts, so no orphan data is left behind.
- **USER to DJANGO_SESSION (dotted):** a conceptual link only. Django stores the user id inside the session data, not as a database foreign key.

**Fields**
- **email:** stored lowercase and protected by a case-insensitive unique constraint, so `A@x.com` and `a@x.com` cannot both